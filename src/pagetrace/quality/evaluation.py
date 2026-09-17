"""Consolidated deterministic quality aggregation and regression gates."""

from __future__ import annotations

from collections.abc import Iterable

from pagetrace.ocr import OcrEvaluation
from pagetrace.qa import QaStatus
from pagetrace.quality.models import (
    DEFAULT_QUALITY_PROCESSOR,
    QUALITY_SCHEMA_VERSION,
    EvaluationStatus,
    FindingSeverity,
    GateResult,
    MetricObservation,
    QualityDimension,
    QualityFinding,
    QualityMetricName,
    QualityProcessorDescriptor,
    QualityReport,
    QualitySuite,
    RegressionResult,
    TextQualityCase,
    compare_metric,
    metric_degradation,
    quality_content_fingerprint_for,
    quality_report_id_for,
    quality_report_status_for,
)


def text_quality_case(case_id: str, evaluation: OcrEvaluation) -> TextQualityCase:
    """Convert exact OCR/text metrics into a named consolidated fixture."""

    if not isinstance(evaluation, OcrEvaluation):
        raise ValueError("evaluation must be an OcrEvaluation")
    return TextQualityCase(
        case_id=case_id,
        exact_match=evaluation.exact_match,
        character_error_rate=evaluation.character_error_rate,
        word_error_rate=evaluation.word_error_rate,
    )


def evaluate_quality(
    suite: QualitySuite,
    *,
    baseline: QualityReport | None = None,
    processor: QualityProcessorDescriptor = DEFAULT_QUALITY_PROCESSOR,
) -> QualityReport:
    """Aggregate cross-stage metrics, gates, regressions, findings, and resource counts."""

    if not isinstance(suite, QualitySuite):
        raise ValueError("suite must be a QualitySuite")
    if baseline is not None and not isinstance(baseline, QualityReport):
        raise ValueError("baseline must be a QualityReport or None")
    if not isinstance(processor, QualityProcessorDescriptor):
        raise ValueError("processor must be a QualityProcessorDescriptor")

    observations: dict[QualityMetricName, MetricObservation] = {}
    findings: list[QualityFinding] = []
    _evaluate_text(suite, observations, findings)
    _evaluate_retrieval(suite, observations, findings)
    _evaluate_answers(suite, observations, findings)
    _evaluate_human_reviews(suite, observations, findings)

    metrics = tuple(sorted(observations.values(), key=lambda item: item.metric.value))
    gates = _evaluate_gates(suite, observations, findings)
    regressions = _evaluate_regressions(suite, observations, baseline, findings)
    finding_tuple = tuple(
        sorted(
            findings,
            key=lambda item: (
                item.dimension.value,
                item.case_id or "",
                item.code,
                item.message,
            ),
        )
    )
    content_fingerprint = quality_content_fingerprint_for(
        metrics, gates, regressions, finding_tuple
    )
    baseline_id = baseline.report_id if baseline is not None else None
    return QualityReport(
        schema_version=QUALITY_SCHEMA_VERSION,
        report_id=quality_report_id_for(
            suite.suite_id,
            processor,
            suite.policy,
            baseline_id,
            content_fingerprint,
        ),
        suite_id=suite.suite_id,
        processor=processor,
        policy=suite.policy,
        baseline_report_id=baseline_id,
        status=quality_report_status_for(gates, regressions),
        metrics=metrics,
        gates=gates,
        regressions=regressions,
        findings=finding_tuple,
        content_fingerprint=content_fingerprint,
    )


def _evaluate_text(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    findings: list[QualityFinding],
) -> None:
    if not suite.text_cases:
        return
    cases = suite.text_cases
    _observe(
        observations,
        QualityMetricName.TEXT_EXACT_MATCH_RATE,
        sum(case.exact_match for case in cases) / len(cases),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.TEXT_MEAN_CHARACTER_ERROR_RATE,
        _mean(case.character_error_rate for case in cases),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.TEXT_MEAN_WORD_ERROR_RATE,
        _mean(case.word_error_rate for case in cases),
        len(cases),
    )
    for case in cases:
        if not case.exact_match:
            findings.append(
                QualityFinding(
                    code="text_mismatch",
                    severity=FindingSeverity.WARNING,
                    dimension=QualityDimension.TEXT,
                    case_id=case.case_id,
                    message="Predicted text does not exactly match the reference.",
                )
            )


def _evaluate_retrieval(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    findings: list[QualityFinding],
) -> None:
    cases = tuple(case for evaluation in suite.retrieval_evaluations for case in evaluation.cases)
    if not cases:
        return
    for metric, attribute in (
        (QualityMetricName.RETRIEVAL_MEAN_RECIPROCAL_RANK, "reciprocal_rank"),
        (QualityMetricName.RETRIEVAL_MEAN_PRECISION, "precision"),
        (QualityMetricName.RETRIEVAL_MEAN_RECALL, "recall"),
        (QualityMetricName.RETRIEVAL_MEAN_AVERAGE_PRECISION, "average_precision"),
        (QualityMetricName.RETRIEVAL_MEAN_NDCG, "ndcg"),
    ):
        _observe(
            observations,
            metric,
            _mean(getattr(case, attribute) for case in cases),
            len(cases),
        )
    for evaluation in suite.retrieval_evaluations:
        for case in evaluation.cases:
            if case.recall == 0:
                findings.append(
                    QualityFinding(
                        code="retrieval_zero_recall",
                        severity=FindingSeverity.WARNING,
                        dimension=QualityDimension.RETRIEVAL,
                        case_id=case.query_id,
                        message=(
                            "No judged relevant chunk was retrieved at the configured cutoff."
                        ),
                    )
                )


def _evaluate_answers(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    findings: list[QualityFinding],
) -> None:
    cases = suite.answer_cases
    if not cases:
        return
    status_matches = [case.result.status is case.expected_status for case in cases]
    _observe(
        observations,
        QualityMetricName.ANSWER_STATUS_ACCURACY,
        sum(status_matches) / len(status_matches),
        len(status_matches),
    )
    _observe(
        observations,
        QualityMetricName.PROVENANCE_SUPPORTED_ANSWER_RATE,
        1.0,
        len(cases),
    )

    exactly_judged = tuple(case for case in cases if case.acceptable_answers)
    if exactly_judged:
        exact_matches = sum(
            case.result.answer in case.acceptable_answers for case in exactly_judged
        )
        _observe(
            observations,
            QualityMetricName.ANSWER_EXACT_MATCH_RATE,
            exact_matches / len(exactly_judged),
            len(exactly_judged),
        )

    relevance_judged = tuple(case for case in cases if case.relevant_chunk_ids)
    if relevance_judged:
        precisions: list[float] = []
        recalls: list[float] = []
        for case in relevance_judged:
            relevant = set(case.relevant_chunk_ids)
            cited = {citation.chunk_id for citation in case.result.citations}
            relevant_cited = len(relevant & cited)
            precisions.append(relevant_cited / len(cited) if cited else 0.0)
            recalls.append(relevant_cited / len(relevant))
            if cited - relevant:
                findings.append(
                    QualityFinding(
                        code="citation_not_judged_relevant",
                        severity=FindingSeverity.WARNING,
                        dimension=QualityDimension.PROVENANCE,
                        case_id=case.case_id,
                        message="The answer cites a chunk not judged relevant for this case.",
                    )
                )
            if relevant - cited:
                findings.append(
                    QualityFinding(
                        code="relevant_evidence_not_cited",
                        severity=FindingSeverity.WARNING,
                        dimension=QualityDimension.PROVENANCE,
                        case_id=case.case_id,
                        message="The answer omits at least one judged relevant chunk.",
                    )
                )
        _observe(
            observations,
            QualityMetricName.PROVENANCE_CITATION_PRECISION,
            _mean(precisions),
            len(relevance_judged),
        )
        _observe(
            observations,
            QualityMetricName.PROVENANCE_CITATION_RECALL,
            _mean(recalls),
            len(relevance_judged),
        )

    expected_abstentions = tuple(
        case for case in cases if case.expected_status is QaStatus.ABSTAINED
    )
    if expected_abstentions:
        false_answers = sum(
            case.result.status is QaStatus.ANSWERED for case in expected_abstentions
        )
        _observe(
            observations,
            QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
            false_answers / len(expected_abstentions),
            len(expected_abstentions),
        )

    for case, status_matches_case in zip(cases, status_matches, strict=True):
        if not status_matches_case:
            false_answer = (
                case.expected_status is QaStatus.ABSTAINED
                and case.result.status is QaStatus.ANSWERED
            )
            findings.append(
                QualityFinding(
                    code="false_answer" if false_answer else "unexpected_abstention",
                    severity=FindingSeverity.ERROR,
                    dimension=QualityDimension.SAFETY,
                    case_id=case.case_id,
                    message=(
                        "The system answered a case expected to abstain."
                        if false_answer
                        else "The system abstained from a case expected to be answered."
                    ),
                )
            )
        if case.acceptable_answers and case.result.answer not in case.acceptable_answers:
            findings.append(
                QualityFinding(
                    code="answer_exact_mismatch",
                    severity=FindingSeverity.WARNING,
                    dimension=QualityDimension.ANSWER,
                    case_id=case.case_id,
                    message="Answer text is outside the case's accepted exact-answer set.",
                )
            )

    _observe(
        observations,
        QualityMetricName.COST_QUERY_TOKENS,
        float(sum(len(case.result.retrieval.query_tokens) for case in cases)),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.COST_RETRIEVED_CHARACTERS,
        float(sum(len(hit.text) for case in cases for hit in case.result.retrieval.hits)),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.COST_ANSWER_CHARACTERS,
        float(sum(len(case.result.answer or "") for case in cases)),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.COST_EVIDENCE_CHARACTERS,
        float(sum(len(citation.excerpt) for case in cases for citation in case.result.citations)),
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.COST_EXTERNAL_REQUESTS,
        0.0,
        len(cases),
    )
    _observe(
        observations,
        QualityMetricName.COST_ESTIMATED_EXTERNAL_USD,
        0.0,
        len(cases),
    )


def _evaluate_human_reviews(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    findings: list[QualityFinding],
) -> None:
    reviews = suite.human_reviews
    if not reviews:
        return
    for metric, attribute in (
        (QualityMetricName.HUMAN_RELEVANCE, "relevance"),
        (QualityMetricName.HUMAN_CORRECTNESS, "correctness"),
        (QualityMetricName.HUMAN_COMPLETENESS, "completeness"),
        (QualityMetricName.HUMAN_TRACEABILITY, "traceability"),
    ):
        _observe(
            observations,
            metric,
            _mean(float(getattr(review, attribute)) for review in reviews),
            len(reviews),
        )
    for review in reviews:
        if (
            min(
                review.relevance,
                review.correctness,
                review.completeness,
                review.traceability,
            )
            <= 2
        ):
            findings.append(
                QualityFinding(
                    code="low_human_review_score",
                    severity=FindingSeverity.WARNING,
                    dimension=QualityDimension.HUMAN,
                    case_id=review.case_id,
                    message="At least one human-review rubric score is 2 or lower.",
                )
            )


def _evaluate_gates(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    findings: list[QualityFinding],
) -> tuple[GateResult, ...]:
    results: list[GateResult] = []
    for gate in suite.policy.gates:
        observation = observations.get(gate.metric)
        if observation is None or observation.sample_count < gate.minimum_samples:
            result = GateResult(gate, EvaluationStatus.NOT_EVALUATED, None, 0)
        else:
            passed = compare_metric(observation.value, gate.comparator, gate.threshold)
            status = EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED
            result = GateResult(gate, status, observation.value, observation.sample_count)
            if not passed:
                findings.append(
                    QualityFinding(
                        code="quality_gate_failed",
                        severity=FindingSeverity.ERROR,
                        dimension=_dimension_for_metric(gate.metric),
                        case_id=None,
                        message=f"Quality gate failed for {gate.metric.value}.",
                    )
                )
        results.append(result)
    return tuple(results)


def _evaluate_regressions(
    suite: QualitySuite,
    observations: dict[QualityMetricName, MetricObservation],
    baseline: QualityReport | None,
    findings: list[QualityFinding],
) -> tuple[RegressionResult, ...]:
    baseline_metrics = (
        {observation.metric: observation for observation in baseline.metrics}
        if baseline is not None
        else {}
    )
    results: list[RegressionResult] = []
    for rule in suite.policy.regression_rules:
        current = observations.get(rule.metric)
        previous = baseline_metrics.get(rule.metric)
        if (
            current is None
            or previous is None
            or current.sample_count < rule.minimum_samples
            or previous.sample_count < rule.minimum_samples
        ):
            result = RegressionResult(
                rule,
                EvaluationStatus.NOT_EVALUATED,
                None,
                None,
                None,
                0,
                0,
            )
        else:
            degradation = metric_degradation(rule.metric, current.value, previous.value)
            passed = degradation <= rule.maximum_degradation
            status = EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED
            result = RegressionResult(
                rule,
                status,
                current.value,
                previous.value,
                degradation,
                current.sample_count,
                previous.sample_count,
            )
            if not passed:
                findings.append(
                    QualityFinding(
                        code="quality_regression",
                        severity=FindingSeverity.ERROR,
                        dimension=QualityDimension.REGRESSION,
                        case_id=None,
                        message=f"Metric regressed beyond tolerance: {rule.metric.value}.",
                    )
                )
        results.append(result)
    return tuple(results)


def _observe(
    observations: dict[QualityMetricName, MetricObservation],
    metric: QualityMetricName,
    value: float,
    sample_count: int,
) -> None:
    observations[metric] = MetricObservation(metric, round(value, 12), sample_count)


def _mean(values: Iterable[float]) -> float:
    materialized = tuple(values)
    return round(sum(materialized) / len(materialized), 12)


def _dimension_for_metric(metric: QualityMetricName) -> QualityDimension:
    return QualityDimension(metric.value.split(".", 1)[0])
