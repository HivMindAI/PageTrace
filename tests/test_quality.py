from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pytest

from pagetrace.corpus import CorpusArtifact, build_corpus_artifact
from pagetrace.ocr import evaluate_ocr
from pagetrace.qa import QaResult, QaStatus, answer_from_retrieval
from pagetrace.quality import (
    AnswerQualityCase,
    EvaluationStatus,
    FindingSeverity,
    GateResult,
    HumanReview,
    MetricComparator,
    MetricGate,
    MetricObservation,
    QualityDimension,
    QualityFinding,
    QualityIntegrityError,
    QualityMetricName,
    QualityPolicy,
    QualityProcessorDescriptor,
    QualityReport,
    QualityReportStatus,
    QualitySuite,
    RegressionResult,
    RegressionRule,
    TextQualityCase,
    create_quality_suite,
    deserialize_quality_report,
    deserialize_quality_suite,
    evaluate_quality,
    is_quality_report_id,
    is_quality_suite_id,
    metric_degradation,
    serialize_quality_report,
    serialize_quality_suite,
    text_quality_case,
)
from pagetrace.retrieval import (
    RetrievalConfig,
    RetrievalJudgment,
    create_retrieval_dataset,
    evaluate_retrieval,
    rank_corpus,
)
from tests.test_corpus_models import _source


def test_consolidated_quality_report_covers_all_dimensions_and_gates() -> None:
    suite = _full_suite()

    report = evaluate_quality(suite)
    metrics = {observation.metric: observation for observation in report.metrics}

    assert report.status is QualityReportStatus.PASSED
    assert is_quality_suite_id(suite.suite_id)
    assert is_quality_report_id(report.report_id)
    assert metrics[QualityMetricName.TEXT_EXACT_MATCH_RATE].value == 0.5
    assert metrics[QualityMetricName.RETRIEVAL_MEAN_RECALL].value == 0.5
    assert metrics[QualityMetricName.ANSWER_STATUS_ACCURACY].value == 1.0
    assert metrics[QualityMetricName.PROVENANCE_SUPPORTED_ANSWER_RATE].value == 1.0
    assert metrics[QualityMetricName.SAFETY_FALSE_ANSWER_RATE].value == 0.0
    assert metrics[QualityMetricName.HUMAN_CORRECTNESS].value == 3.5
    assert metrics[QualityMetricName.COST_EXTERNAL_REQUESTS].value == 0.0
    assert all(result.status is EvaluationStatus.PASSED for result in report.gates)
    assert {finding.code for finding in report.findings} >= {
        "text_mismatch",
        "retrieval_zero_recall",
        "low_human_review_score",
    }


def test_false_answer_and_failed_gate_are_actionable() -> None:
    corpus = build_corpus_artifact(_source((("alpha answer.",),)))
    answered = answer_from_retrieval(rank_corpus(corpus, "alpha"))
    suite = create_quality_suite(
        answer_cases=(
            AnswerQualityCase(
                "unsafe-case",
                answered,
                QaStatus.ABSTAINED,
            ),
        ),
        policy=QualityPolicy(
            policy_id="safety-gate",
            gates=(
                MetricGate(
                    QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
                    MetricComparator.AT_MOST,
                    0.0,
                ),
            ),
        ),
    )

    report = evaluate_quality(suite)

    assert report.status is QualityReportStatus.FAILED
    assert report.gates[0].status is EvaluationStatus.FAILED
    assert {finding.code for finding in report.findings} >= {
        "false_answer",
        "quality_gate_failed",
    }


def test_missing_metric_or_sample_floor_makes_report_incomplete() -> None:
    suite = create_quality_suite(
        text_cases=(TextQualityCase("text", True, 0.0, 0.0),),
        policy=QualityPolicy(
            policy_id="missing-human",
            gates=(
                MetricGate(
                    QualityMetricName.HUMAN_CORRECTNESS,
                    MetricComparator.AT_LEAST,
                    4.0,
                ),
                MetricGate(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    MetricComparator.AT_LEAST,
                    1.0,
                    minimum_samples=2,
                ),
            ),
        ),
    )

    report = evaluate_quality(suite)

    assert report.status is QualityReportStatus.INCOMPLETE
    assert all(result.status is EvaluationStatus.NOT_EVALUATED for result in report.gates)


def test_observe_only_report_and_directional_regression() -> None:
    baseline_suite = create_quality_suite(text_cases=(TextQualityCase("baseline", True, 0.0, 0.0),))
    baseline = evaluate_quality(baseline_suite)
    assert baseline.status is QualityReportStatus.OBSERVATIONAL

    current_suite = create_quality_suite(
        text_cases=(TextQualityCase("current", False, 1.0, 1.0),),
        policy=QualityPolicy(
            policy_id="no-text-regression",
            regression_rules=(
                RegressionRule(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    maximum_degradation=0.1,
                ),
                RegressionRule(
                    QualityMetricName.TEXT_MEAN_CHARACTER_ERROR_RATE,
                    maximum_degradation=0.1,
                ),
            ),
        ),
    )

    current = evaluate_quality(current_suite, baseline=baseline)

    assert current.status is QualityReportStatus.FAILED
    assert all(result.status is EvaluationStatus.FAILED for result in current.regressions)
    assert current.regressions[0].degradation == 1.0
    assert current.regressions[1].degradation == 1.0
    assert metric_degradation(QualityMetricName.TEXT_EXACT_MATCH_RATE, 0.8, 1.0) == 0.2
    assert metric_degradation(QualityMetricName.TEXT_MEAN_WORD_ERROR_RATE, 0.2, 0.1) == 0.1


def test_regression_without_baseline_is_explicitly_incomplete() -> None:
    suite = create_quality_suite(
        text_cases=(TextQualityCase("text", True, 0.0, 0.0),),
        policy=QualityPolicy(
            policy_id="baseline-required",
            regression_rules=(RegressionRule(QualityMetricName.TEXT_EXACT_MATCH_RATE),),
        ),
    )

    report = evaluate_quality(suite)

    assert report.status is QualityReportStatus.INCOMPLETE
    assert report.regressions[0].status is EvaluationStatus.NOT_EVALUATED


def test_quality_suite_and_report_serialization_are_canonical_and_strict() -> None:
    suite = _full_suite()
    report = evaluate_quality(suite)
    suite_data = serialize_quality_suite(suite)
    report_data = serialize_quality_report(report)

    assert deserialize_quality_suite(suite_data) == suite
    assert serialize_quality_suite(deserialize_quality_suite(suite_data)) == suite_data
    assert deserialize_quality_report(report_data) == report
    assert serialize_quality_report(deserialize_quality_report(report_data)) == report_data

    with pytest.raises(QualityIntegrityError, match="strict UTF-8 JSON"):
        deserialize_quality_suite(b"\xff")
    with pytest.raises(QualityIntegrityError, match="strict UTF-8 JSON"):
        deserialize_quality_report(b'{"status":"passed","status":"failed"}')
    with pytest.raises(QualityIntegrityError, match="fields do not match"):
        deserialize_quality_suite(b"{}")
    with pytest.raises(QualityIntegrityError, match="bytes"):
        deserialize_quality_report("{}")  # type: ignore[arg-type]


def test_quality_serialization_rejects_suite_and_report_tampering() -> None:
    suite = _full_suite()
    suite_payload = json.loads(serialize_quality_suite(suite))
    suite_payload["text_cases"][1]["character_error_rate"] = 0.25
    with pytest.raises(QualityIntegrityError, match="suite_id"):
        deserialize_quality_suite(json.dumps(suite_payload).encode())

    report = evaluate_quality(suite)
    report_payload = json.loads(serialize_quality_report(report))
    report_payload["metrics"][0]["value"] = 0.125
    with pytest.raises(QualityIntegrityError, match="content_fingerprint"):
        deserialize_quality_report(json.dumps(report_payload).encode())

    nonfinite = serialize_quality_report(report).replace(b'"value":0.0', b'"value":NaN', 1)
    with pytest.raises(QualityIntegrityError, match="strict UTF-8 JSON"):
        deserialize_quality_report(nonfinite)


def test_text_evaluation_adapter_preserves_exact_metrics() -> None:
    evaluation = evaluate_ocr("alpha", "alpba")
    case = text_quality_case("fixture", evaluation)

    assert case.exact_match is False
    assert case.character_error_rate == evaluation.character_error_rate
    with pytest.raises(ValueError, match="OcrEvaluation"):
        text_quality_case("fixture", object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TextQualityCase("bad id!", True, 0.0, 0.0),
        lambda: TextQualityCase("case", True, 0.1, 0.0),
        lambda: HumanReview("review", "case", "v1", 0, 5, 5, 5),
        lambda: QualityPolicy(
            gates=(
                MetricGate(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    MetricComparator.AT_LEAST,
                    1.0,
                ),
                MetricGate(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    MetricComparator.AT_MOST,
                    1.0,
                ),
            )
        ),
        lambda: RegressionRule(QualityMetricName.COST_QUERY_TOKENS),
        lambda: MetricObservation(QualityMetricName.TEXT_EXACT_MATCH_RATE, 2.0, 1),
        lambda: GateResult(
            MetricGate(
                QualityMetricName.TEXT_EXACT_MATCH_RATE,
                MetricComparator.AT_LEAST,
                1.0,
            ),
            EvaluationStatus.PASSED,
            0.0,
            1,
        ),
    ],
)
def test_quality_model_contradictions_are_rejected(factory: Callable[[], object]) -> None:
    with pytest.raises(
        ValueError,
        match=r"must|unique|informational|contradicts|outside",
    ):
        factory()


def test_suite_rejects_unknown_human_review_case_and_duplicate_case_ids() -> None:
    answered_case = _answer_cases()[0]
    with pytest.raises(ValueError, match="human reviews must reference"):
        create_quality_suite(
            answer_cases=(answered_case,),
            human_reviews=(HumanReview("review", "other", "v1", 5, 5, 5, 5),),
        )
    with pytest.raises(ValueError, match="globally unique"):
        create_quality_suite(
            text_cases=(TextQualityCase(answered_case.case_id, True, 0.0, 0.0),),
            answer_cases=(answered_case,),
        )


def test_answer_gate_regression_and_finding_validation_boundaries() -> None:
    answered = _answer_cases()[0]
    relevant_id = answered.relevant_chunk_ids[0]
    valid_gate = MetricGate(
        QualityMetricName.TEXT_EXACT_MATCH_RATE,
        MetricComparator.AT_LEAST,
        1.0,
        minimum_samples=2,
    )
    valid_rule = RegressionRule(QualityMetricName.TEXT_EXACT_MATCH_RATE)
    factories: tuple[Callable[[], object], ...] = (
        lambda: QualityProcessorDescriptor(name="other"),
        lambda: QualityProcessorDescriptor(version=""),
        lambda: TextQualityCase("case", cast(bool, 1), 0.0, 0.0),
        lambda: AnswerQualityCase("case", cast(QaResult, object()), QaStatus.ANSWERED),
        lambda: AnswerQualityCase("case", answered.result, cast(QaStatus, "answered")),
        lambda: AnswerQualityCase(
            "case", answered.result, QaStatus.ANSWERED, cast(tuple[str, ...], ["answer"])
        ),
        lambda: AnswerQualityCase("case", answered.result, QaStatus.ANSWERED, ("",)),
        lambda: AnswerQualityCase("case", answered.result, QaStatus.ANSWERED, ("answer", "answer")),
        lambda: AnswerQualityCase("case", answered.result, QaStatus.ABSTAINED, ("answer",)),
        lambda: AnswerQualityCase(
            "case",
            answered.result,
            QaStatus.ANSWERED,
            relevant_chunk_ids=cast(tuple[str, ...], [relevant_id]),
        ),
        lambda: AnswerQualityCase(
            "case",
            answered.result,
            QaStatus.ANSWERED,
            relevant_chunk_ids=("bad",),
        ),
        lambda: AnswerQualityCase(
            "case",
            answered.result,
            QaStatus.ANSWERED,
            relevant_chunk_ids=(relevant_id, relevant_id),
        ),
        lambda: MetricGate(cast(QualityMetricName, "bad"), MetricComparator.AT_LEAST, 1.0),
        lambda: MetricGate(
            QualityMetricName.TEXT_EXACT_MATCH_RATE,
            cast(MetricComparator, "bad"),
            1.0,
        ),
        lambda: MetricGate(
            QualityMetricName.TEXT_EXACT_MATCH_RATE,
            MetricComparator.AT_LEAST,
            float("inf"),
        ),
        lambda: MetricGate(
            QualityMetricName.TEXT_EXACT_MATCH_RATE,
            MetricComparator.AT_LEAST,
            1.0,
            minimum_samples=0,
        ),
        lambda: RegressionRule(cast(QualityMetricName, "bad")),
        lambda: RegressionRule(QualityMetricName.TEXT_EXACT_MATCH_RATE, maximum_degradation=-1),
        lambda: RegressionRule(QualityMetricName.TEXT_EXACT_MATCH_RATE, minimum_samples=0),
        lambda: GateResult(valid_gate, EvaluationStatus.NOT_EVALUATED, 1.0, 2),
        lambda: GateResult(valid_gate, EvaluationStatus.PASSED, None, 2),
        lambda: GateResult(valid_gate, EvaluationStatus.PASSED, 1.0, 1),
        lambda: RegressionResult(valid_rule, EvaluationStatus.NOT_EVALUATED, 1.0, None, None, 0, 0),
        lambda: RegressionResult(valid_rule, EvaluationStatus.PASSED, None, 1.0, 0.0, 1, 1),
        lambda: RegressionResult(valid_rule, EvaluationStatus.PASSED, 1.0, 1.0, 0.0, 0, 1),
        lambda: RegressionResult(valid_rule, EvaluationStatus.PASSED, 0.5, 1.0, 0.25, 1, 1),
        lambda: RegressionResult(valid_rule, EvaluationStatus.PASSED, 0.5, 1.0, 0.5, 1, 1),
        lambda: QualityFinding(
            "finding", cast(FindingSeverity, "error"), QualityDimension.TEXT, None, "message"
        ),
        lambda: QualityFinding(
            "finding", FindingSeverity.ERROR, cast(QualityDimension, "text"), None, "message"
        ),
        lambda: QualityFinding("finding", FindingSeverity.ERROR, QualityDimension.TEXT, None, ""),
    )
    for factory in factories:
        with pytest.raises(ValueError, match=r".+"):
            factory()


def test_suite_and_report_models_reject_identity_and_state_contradictions() -> None:
    suite = _full_suite()
    report = evaluate_quality(suite)
    suite_factories: tuple[Callable[[], object], ...] = (
        lambda: replace(suite, schema_version=2),
        lambda: replace(suite, suite_id="bad"),
        lambda: replace(suite, text_cases=cast(tuple[TextQualityCase, ...], [])),
        lambda: replace(
            suite,
            text_cases=(),
            retrieval_evaluations=(),
            answer_cases=(),
            human_reviews=(),
        ),
        lambda: replace(
            suite,
            retrieval_evaluations=(
                suite.retrieval_evaluations[0],
                suite.retrieval_evaluations[0],
            ),
        ),
        lambda: replace(
            suite,
            human_reviews=(suite.human_reviews[0], suite.human_reviews[0]),
        ),
        lambda: replace(suite, policy=cast(QualityPolicy, object())),
        lambda: replace(suite, suite_id=f"quality-suite-sha256-{'0' * 64}"),
    )
    report_factories: tuple[Callable[[], QualityReport], ...] = (
        lambda: replace(report, schema_version=2),
        lambda: replace(report, report_id="bad"),
        lambda: replace(report, suite_id="bad"),
        lambda: replace(report, processor=cast(QualityProcessorDescriptor, object())),
        lambda: replace(report, policy=cast(QualityPolicy, object())),
        lambda: replace(report, baseline_report_id="bad"),
        lambda: replace(report, status=QualityReportStatus.FAILED),
        lambda: replace(report, metrics=tuple(reversed(report.metrics))),
        lambda: replace(report, gates=()),
        lambda: replace(report, content_fingerprint="0" * 64),
        lambda: replace(report, report_id=f"quality-report-sha256-{'0' * 64}"),
    )
    for factory in (*suite_factories, *report_factories):
        with pytest.raises((AttributeError, ValueError), match=r".+"):
            factory()


def test_quality_deserialization_rejects_nested_and_primitive_type_tampering() -> None:
    suite = _full_suite()
    base = json.loads(serialize_quality_suite(suite))
    mutations: tuple[tuple[str, object], ...] = (
        ("text_cases", {}),
        ("text_case_object", []),
        ("text_case_boolean", "yes"),
        ("human_review_integer", True),
        ("gate_number", True),
    )
    for name, replacement in mutations:
        payload = json.loads(json.dumps(base))
        if name == "text_cases":
            payload["text_cases"] = replacement
        elif name == "text_case_object":
            payload["text_cases"][0] = replacement
        elif name == "text_case_boolean":
            payload["text_cases"][0]["exact_match"] = replacement
        elif name == "human_review_integer":
            payload["human_reviews"][0]["relevance"] = replacement
        else:
            payload["policy"]["gates"][0]["threshold"] = replacement
        with pytest.raises(QualityIntegrityError):
            deserialize_quality_suite(json.dumps(payload).encode())

    nested_qa = json.loads(json.dumps(base))
    nested_qa["answer_cases"][0]["result"]["content_fingerprint"] = "0" * 64
    with pytest.raises(QualityIntegrityError, match="nested quality input"):
        deserialize_quality_suite(json.dumps(nested_qa).encode())

    nested_retrieval = json.loads(json.dumps(base))
    nested_retrieval["retrieval_evaluations"][0]["content_fingerprint"] = "0" * 64
    with pytest.raises(QualityIntegrityError, match="nested quality input"):
        deserialize_quality_suite(json.dumps(nested_retrieval).encode())


def _full_suite() -> QualitySuite:
    corpus = build_corpus_artifact(_source((("alpha answer.", "beta evidence."),)))
    retrieval_dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (
            RetrievalJudgment("found", "alpha", (corpus.chunks[0].chunk_id,)),
            RetrievalJudgment("missed", "missing", (corpus.chunks[0].chunk_id,)),
        ),
    )
    retrieval_evaluation = evaluate_retrieval(
        corpus, retrieval_dataset, configuration=RetrievalConfig(top_k=1)
    )
    answer_cases = _answer_cases(corpus)
    policy = QualityPolicy(
        policy_id="portfolio-v1",
        gates=(
            MetricGate(
                QualityMetricName.TEXT_EXACT_MATCH_RATE,
                MetricComparator.AT_LEAST,
                0.5,
            ),
            MetricGate(
                QualityMetricName.RETRIEVAL_MEAN_RECALL,
                MetricComparator.AT_LEAST,
                0.5,
            ),
            MetricGate(
                QualityMetricName.ANSWER_STATUS_ACCURACY,
                MetricComparator.AT_LEAST,
                1.0,
            ),
            MetricGate(
                QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
                MetricComparator.AT_MOST,
                0.0,
            ),
            MetricGate(
                QualityMetricName.HUMAN_CORRECTNESS,
                MetricComparator.AT_LEAST,
                3.5,
            ),
        ),
    )
    return create_quality_suite(
        text_cases=(
            text_quality_case("exact-text", evaluate_ocr("alpha", "alpha")),
            text_quality_case("changed-text", evaluate_ocr("alpha", "alpba")),
        ),
        retrieval_evaluations=(retrieval_evaluation,),
        answer_cases=answer_cases,
        human_reviews=(
            HumanReview("review-good", "answer", "v1", 5, 5, 5, 5),
            HumanReview("review-low", "abstain", "v1", 2, 2, 2, 2),
        ),
        policy=policy,
    )


def _answer_cases(
    corpus: CorpusArtifact | None = None,
) -> tuple[AnswerQualityCase, AnswerQualityCase]:
    if corpus is None:
        corpus = build_corpus_artifact(_source((("alpha answer.",),)))
    answered = answer_from_retrieval(rank_corpus(corpus, "alpha"))
    abstained = answer_from_retrieval(rank_corpus(corpus, "missing"))
    return (
        AnswerQualityCase(
            "answer",
            answered,
            QaStatus.ANSWERED,
            acceptable_answers=(answered.answer or "",),
            relevant_chunk_ids=(corpus.chunks[0].chunk_id,),
        ),
        AnswerQualityCase("abstain", abstained, QaStatus.ABSTAINED),
    )
