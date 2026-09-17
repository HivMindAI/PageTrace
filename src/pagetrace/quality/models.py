"""Immutable schemas for PageTrace quality suites and reports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from pagetrace.corpus import is_chunk_id
from pagetrace.qa import QaResult, QaStatus, serialize_qa_result
from pagetrace.retrieval import RetrievalEvaluation, serialize_retrieval_evaluation

QUALITY_SCHEMA_VERSION = 1
QUALITY_PROCESSOR_NAME = "pagetrace-quality"
QUALITY_PROCESSOR_VERSION = "1"
_SUITE_ID_PATTERN = re.compile(r"^quality-suite-sha256-[0-9a-f]{64}$")
_REPORT_ID_PATTERN = re.compile(r"^quality-report-sha256-[0-9a-f]{64}$")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class QualityDimension(StrEnum):
    """Evaluation dimensions consolidated by Milestone 7."""

    TEXT = "text"
    RETRIEVAL = "retrieval"
    ANSWER = "answer"
    PROVENANCE = "provenance"
    SAFETY = "safety"
    HUMAN = "human"
    COST = "cost"
    REGRESSION = "regression"


class QualityMetricName(StrEnum):
    """Stable metric names emitted by the quality evaluator."""

    TEXT_EXACT_MATCH_RATE = "text.exact_match_rate"
    TEXT_MEAN_CHARACTER_ERROR_RATE = "text.mean_character_error_rate"
    TEXT_MEAN_WORD_ERROR_RATE = "text.mean_word_error_rate"
    RETRIEVAL_MEAN_RECIPROCAL_RANK = "retrieval.mean_reciprocal_rank"
    RETRIEVAL_MEAN_PRECISION = "retrieval.mean_precision"
    RETRIEVAL_MEAN_RECALL = "retrieval.mean_recall"
    RETRIEVAL_MEAN_AVERAGE_PRECISION = "retrieval.mean_average_precision"
    RETRIEVAL_MEAN_NDCG = "retrieval.mean_ndcg"
    ANSWER_STATUS_ACCURACY = "answer.status_accuracy"
    ANSWER_EXACT_MATCH_RATE = "answer.exact_match_rate"
    PROVENANCE_CITATION_PRECISION = "provenance.citation_precision"
    PROVENANCE_CITATION_RECALL = "provenance.citation_recall"
    PROVENANCE_SUPPORTED_ANSWER_RATE = "provenance.supported_answer_rate"
    SAFETY_FALSE_ANSWER_RATE = "safety.false_answer_rate"
    HUMAN_RELEVANCE = "human.mean_relevance"
    HUMAN_CORRECTNESS = "human.mean_correctness"
    HUMAN_COMPLETENESS = "human.mean_completeness"
    HUMAN_TRACEABILITY = "human.mean_traceability"
    COST_QUERY_TOKENS = "cost.query_tokens"
    COST_RETRIEVED_CHARACTERS = "cost.retrieved_characters"
    COST_ANSWER_CHARACTERS = "cost.answer_characters"
    COST_EVIDENCE_CHARACTERS = "cost.evidence_characters"
    COST_EXTERNAL_REQUESTS = "cost.external_requests"
    COST_ESTIMATED_EXTERNAL_USD = "cost.estimated_external_usd"


class MetricComparator(StrEnum):
    """How an observed metric is compared with a quality threshold."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class EvaluationStatus(StrEnum):
    """Outcome of one gate or regression check."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


class QualityReportStatus(StrEnum):
    """Aggregate quality-report outcome."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    OBSERVATIONAL = "observational"


class FindingSeverity(StrEnum):
    """Stable severity for actionable quality findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityProcessorDescriptor:
    """Versioned identity for report aggregation semantics."""

    name: str = QUALITY_PROCESSOR_NAME
    version: str = QUALITY_PROCESSOR_VERSION

    def __post_init__(self) -> None:
        if self.name != QUALITY_PROCESSOR_NAME:
            raise ValueError(f"quality processor name must be {QUALITY_PROCESSOR_NAME}")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("quality processor version must not be empty")


DEFAULT_QUALITY_PROCESSOR = QualityProcessorDescriptor()


@dataclass(frozen=True, slots=True)
class TextQualityCase:
    """Exact text and edit-rate measurements for one named fixture."""

    case_id: str
    exact_match: bool
    character_error_rate: float
    word_error_rate: float

    def __post_init__(self) -> None:
        _validate_safe_id(self.case_id, "text case_id")
        if not isinstance(self.exact_match, bool):
            raise ValueError("exact_match must be a boolean")
        for name, value in (
            ("character_error_rate", self.character_error_rate),
            ("word_error_rate", self.word_error_rate),
        ):
            _validate_nonnegative_number(value, name)
        if self.exact_match and (self.character_error_rate != 0 or self.word_error_rate != 0):
            raise ValueError("exact text matches must have zero error rates")


@dataclass(frozen=True, slots=True)
class AnswerQualityCase:
    """Expected answer behavior and relevance judgments for one QA result."""

    case_id: str
    result: QaResult
    expected_status: QaStatus
    acceptable_answers: tuple[str, ...] = ()
    relevant_chunk_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_safe_id(self.case_id, "answer case_id")
        if not isinstance(self.result, QaResult):
            raise ValueError("result must be a QaResult")
        if not isinstance(self.expected_status, QaStatus):
            raise ValueError("expected_status must be a QaStatus")
        if not isinstance(self.acceptable_answers, tuple):
            raise ValueError("acceptable_answers must be an immutable tuple")
        if any(not isinstance(answer, str) or not answer for answer in self.acceptable_answers):
            raise ValueError("acceptable_answers must contain non-empty strings")
        if len(set(self.acceptable_answers)) != len(self.acceptable_answers):
            raise ValueError("acceptable_answers must be unique")
        if self.acceptable_answers and self.expected_status is not QaStatus.ANSWERED:
            raise ValueError("acceptable answers require an expected answered status")
        if not isinstance(self.relevant_chunk_ids, tuple):
            raise ValueError("relevant_chunk_ids must be an immutable tuple")
        if any(not is_chunk_id(chunk_id) for chunk_id in self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must be canonical chunk identifiers")
        if len(set(self.relevant_chunk_ids)) != len(self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must be unique")


@dataclass(frozen=True, slots=True)
class HumanReview:
    """Structured 1-to-5 human rubric without free-text or reviewer identity."""

    review_id: str
    case_id: str
    rubric_version: str
    relevance: int
    correctness: int
    completeness: int
    traceability: int

    def __post_init__(self) -> None:
        _validate_safe_id(self.review_id, "review_id")
        _validate_safe_id(self.case_id, "human review case_id")
        _validate_safe_id(self.rubric_version, "rubric_version")
        for name, value in (
            ("relevance", self.relevance),
            ("correctness", self.correctness),
            ("completeness", self.completeness),
            ("traceability", self.traceability),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f"{name} must be an integer from 1 to 5")


@dataclass(frozen=True, slots=True)
class MetricGate:
    """A static threshold with an explicit sample floor."""

    metric: QualityMetricName
    comparator: MetricComparator
    threshold: float
    minimum_samples: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.metric, QualityMetricName):
            raise ValueError("gate metric must be a QualityMetricName")
        if not isinstance(self.comparator, MetricComparator):
            raise ValueError("gate comparator must be a MetricComparator")
        _validate_finite_number(self.threshold, "gate threshold")
        _validate_minimum_samples(self.minimum_samples)


@dataclass(frozen=True, slots=True)
class RegressionRule:
    """Maximum allowed directional degradation from a baseline report."""

    metric: QualityMetricName
    maximum_degradation: float = 0.0
    minimum_samples: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.metric, QualityMetricName):
            raise ValueError("regression metric must be a QualityMetricName")
        _validate_nonnegative_number(self.maximum_degradation, "maximum_degradation")
        _validate_minimum_samples(self.minimum_samples)
        if metric_direction(self.metric) == 0:
            raise ValueError("informational metrics cannot have regression rules")


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    """Named quality gates and baseline-regression rules."""

    policy_id: str = "observe-only"
    gates: tuple[MetricGate, ...] = ()
    regression_rules: tuple[RegressionRule, ...] = ()

    def __post_init__(self) -> None:
        _validate_safe_id(self.policy_id, "policy_id")
        if not isinstance(self.gates, tuple) or not isinstance(self.regression_rules, tuple):
            raise ValueError("quality policy collections must be immutable tuples")
        if len({gate.metric for gate in self.gates}) != len(self.gates):
            raise ValueError("quality policy gates must have unique metrics")
        if len({rule.metric for rule in self.regression_rules}) != len(self.regression_rules):
            raise ValueError("regression rules must have unique metrics")


@dataclass(frozen=True, slots=True)
class QualitySuite:
    """Versioned automated fixtures, judgments, human reviews, and policy."""

    schema_version: int
    suite_id: str
    text_cases: tuple[TextQualityCase, ...]
    retrieval_evaluations: tuple[RetrievalEvaluation, ...]
    answer_cases: tuple[AnswerQualityCase, ...]
    human_reviews: tuple[HumanReview, ...]
    policy: QualityPolicy

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported quality schema version: {self.schema_version}")
        if not is_quality_suite_id(self.suite_id):
            raise ValueError("suite_id is not canonical")
        for name, value in (
            ("text_cases", self.text_cases),
            ("retrieval_evaluations", self.retrieval_evaluations),
            ("answer_cases", self.answer_cases),
            ("human_reviews", self.human_reviews),
        ):
            if not isinstance(value, tuple):
                raise ValueError(f"{name} must be an immutable tuple")
        if not (self.text_cases or self.retrieval_evaluations or self.answer_cases):
            raise ValueError("quality suite must contain an automated evaluation input")
        case_ids = [case.case_id for case in self.text_cases]
        case_ids.extend(case.case_id for case in self.answer_cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("quality case IDs must be globally unique")
        evaluation_ids = [evaluation.evaluation_id for evaluation in self.retrieval_evaluations]
        if len(set(evaluation_ids)) != len(evaluation_ids):
            raise ValueError("retrieval evaluations must be unique")
        review_ids = [review.review_id for review in self.human_reviews]
        if len(set(review_ids)) != len(review_ids):
            raise ValueError("human review IDs must be unique")
        answer_case_ids = {case.case_id for case in self.answer_cases}
        if any(review.case_id not in answer_case_ids for review in self.human_reviews):
            raise ValueError("human reviews must reference answer cases in the suite")
        if not isinstance(self.policy, QualityPolicy):
            raise ValueError("policy must be a QualityPolicy")
        if self.suite_id != quality_suite_id_for(
            self.text_cases,
            self.retrieval_evaluations,
            self.answer_cases,
            self.human_reviews,
            self.policy,
        ):
            raise ValueError("suite_id does not match suite content")


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One deterministic aggregate metric and its sample count."""

    metric: QualityMetricName
    value: float
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric, QualityMetricName):
            raise ValueError("observation metric must be a QualityMetricName")
        _validate_finite_number(self.value, "observation value")
        _validate_minimum_samples(self.sample_count)
        lower, upper = metric_bounds(self.metric)
        if self.value < lower or (upper is not None and self.value > upper):
            raise ValueError(f"observation value is outside bounds for {self.metric.value}")


@dataclass(frozen=True, slots=True)
class GateResult:
    """Evaluated or explicitly unavailable static metric gate."""

    gate: MetricGate
    status: EvaluationStatus
    observed_value: float | None
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.gate, MetricGate) or not isinstance(self.status, EvaluationStatus):
            raise ValueError("gate result contains invalid types")
        if self.status is EvaluationStatus.NOT_EVALUATED:
            if self.observed_value is not None or self.sample_count != 0:
                raise ValueError("unevaluated gates cannot contain observations")
            return
        if self.observed_value is None:
            raise ValueError("evaluated gates require an observed value")
        _validate_finite_number(self.observed_value, "gate observed_value")
        if self.sample_count < self.gate.minimum_samples:
            raise ValueError("evaluated gate does not meet its sample floor")
        passed = compare_metric(self.observed_value, self.gate.comparator, self.gate.threshold)
        expected = EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED
        if self.status is not expected:
            raise ValueError("gate status contradicts its observation and threshold")


@dataclass(frozen=True, slots=True)
class RegressionResult:
    """Directional comparison with one metric in a baseline report."""

    rule: RegressionRule
    status: EvaluationStatus
    current_value: float | None
    baseline_value: float | None
    degradation: float | None
    current_samples: int
    baseline_samples: int

    def __post_init__(self) -> None:
        if not isinstance(self.rule, RegressionRule) or not isinstance(
            self.status, EvaluationStatus
        ):
            raise ValueError("regression result contains invalid types")
        if self.status is EvaluationStatus.NOT_EVALUATED:
            if (
                any(
                    value is not None
                    for value in (self.current_value, self.baseline_value, self.degradation)
                )
                or self.current_samples != 0
                or self.baseline_samples != 0
            ):
                raise ValueError("unevaluated regressions cannot contain observations")
            return
        if self.current_value is None or self.baseline_value is None or self.degradation is None:
            raise ValueError("evaluated regressions require current, baseline, and degradation")
        for name, value in (
            ("current_value", self.current_value),
            ("baseline_value", self.baseline_value),
            ("degradation", self.degradation),
        ):
            _validate_finite_number(value, name)
        if min(self.current_samples, self.baseline_samples) < self.rule.minimum_samples:
            raise ValueError("evaluated regression does not meet its sample floor")
        expected_degradation = metric_degradation(
            self.rule.metric, self.current_value, self.baseline_value
        )
        if self.degradation != expected_degradation:
            raise ValueError("regression degradation does not match metric direction")
        expected = (
            EvaluationStatus.PASSED
            if self.degradation <= self.rule.maximum_degradation
            else EvaluationStatus.FAILED
        )
        if self.status is not expected:
            raise ValueError("regression status contradicts its allowed degradation")


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """Stable case-level or report-level diagnostic."""

    code: str
    severity: FindingSeverity
    dimension: QualityDimension
    case_id: str | None
    message: str

    def __post_init__(self) -> None:
        _validate_safe_id(self.code, "finding code")
        if not isinstance(self.severity, FindingSeverity):
            raise ValueError("finding severity must be a FindingSeverity")
        if not isinstance(self.dimension, QualityDimension):
            raise ValueError("finding dimension must be a QualityDimension")
        if self.case_id is not None:
            _validate_safe_id(self.case_id, "finding case_id")
        if not isinstance(self.message, str) or not self.message or len(self.message) > 500:
            raise ValueError("finding message must contain 1 to 500 characters")


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Canonical metrics, gates, regressions, and findings for one suite."""

    schema_version: int
    report_id: str
    suite_id: str
    processor: QualityProcessorDescriptor
    policy: QualityPolicy
    baseline_report_id: str | None
    status: QualityReportStatus
    metrics: tuple[MetricObservation, ...]
    gates: tuple[GateResult, ...]
    regressions: tuple[RegressionResult, ...]
    findings: tuple[QualityFinding, ...]
    content_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported quality schema version: {self.schema_version}")
        if not is_quality_report_id(self.report_id):
            raise ValueError("report_id is not canonical")
        if not is_quality_suite_id(self.suite_id):
            raise ValueError("suite_id is not canonical")
        if not isinstance(self.processor, QualityProcessorDescriptor):
            raise ValueError("processor must be a QualityProcessorDescriptor")
        if not isinstance(self.policy, QualityPolicy):
            raise ValueError("policy must be a QualityPolicy")
        if self.baseline_report_id is not None and not is_quality_report_id(
            self.baseline_report_id
        ):
            raise ValueError("baseline_report_id is not canonical")
        if not isinstance(self.status, QualityReportStatus):
            raise ValueError("status must be a QualityReportStatus")
        for name, value in (
            ("metrics", self.metrics),
            ("gates", self.gates),
            ("regressions", self.regressions),
            ("findings", self.findings),
        ):
            if not isinstance(value, tuple):
                raise ValueError(f"{name} must be an immutable tuple")
        metric_names = tuple(observation.metric for observation in self.metrics)
        if metric_names != tuple(sorted(set(metric_names), key=lambda item: item.value)):
            raise ValueError("report metrics must be unique and sorted")
        if tuple(result.gate for result in self.gates) != self.policy.gates:
            raise ValueError("gate results must match policy gate order")
        if tuple(result.rule for result in self.regressions) != self.policy.regression_rules:
            raise ValueError("regression results must match policy rule order")
        if self.baseline_report_id is None and any(
            result.status is not EvaluationStatus.NOT_EVALUATED for result in self.regressions
        ):
            raise ValueError("regressions require a baseline report")
        expected_status = quality_report_status_for(self.gates, self.regressions)
        if self.status is not expected_status:
            raise ValueError("report status contradicts gate and regression outcomes")
        expected_content = quality_content_fingerprint_for(
            self.metrics, self.gates, self.regressions, self.findings
        )
        if self.content_fingerprint != expected_content:
            raise ValueError("content_fingerprint must match quality results")
        if self.report_id != quality_report_id_for(
            self.suite_id,
            self.processor,
            self.policy,
            self.baseline_report_id,
            self.content_fingerprint,
        ):
            raise ValueError("report_id does not match report inputs")


def create_quality_suite(
    *,
    text_cases: tuple[TextQualityCase, ...] = (),
    retrieval_evaluations: tuple[RetrievalEvaluation, ...] = (),
    answer_cases: tuple[AnswerQualityCase, ...] = (),
    human_reviews: tuple[HumanReview, ...] = (),
    policy: QualityPolicy | None = None,
) -> QualitySuite:
    selected_policy = DEFAULT_QUALITY_POLICY if policy is None else policy
    suite_id = quality_suite_id_for(
        text_cases, retrieval_evaluations, answer_cases, human_reviews, selected_policy
    )
    return QualitySuite(
        schema_version=QUALITY_SCHEMA_VERSION,
        suite_id=suite_id,
        text_cases=text_cases,
        retrieval_evaluations=retrieval_evaluations,
        answer_cases=answer_cases,
        human_reviews=human_reviews,
        policy=selected_policy,
    )


def is_quality_suite_id(value: str) -> bool:
    return isinstance(value, str) and _SUITE_ID_PATTERN.fullmatch(value) is not None


def is_quality_report_id(value: str) -> bool:
    return isinstance(value, str) and _REPORT_ID_PATTERN.fullmatch(value) is not None


def quality_suite_id_for(
    text_cases: tuple[TextQualityCase, ...],
    retrieval_evaluations: tuple[RetrievalEvaluation, ...],
    answer_cases: tuple[AnswerQualityCase, ...],
    human_reviews: tuple[HumanReview, ...],
    policy: QualityPolicy,
) -> str:
    payload = {
        "answer_cases": [answer_case_payload(case) for case in answer_cases],
        "human_reviews": [human_review_payload(review) for review in human_reviews],
        "policy": policy_payload(policy),
        "retrieval_evaluations": [
            json.loads(serialize_retrieval_evaluation(evaluation))
            for evaluation in retrieval_evaluations
        ],
        "schema_version": QUALITY_SCHEMA_VERSION,
        "text_cases": [text_case_payload(case) for case in text_cases],
        "type": "pagetrace_quality_suite",
    }
    return f"quality-suite-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def quality_content_fingerprint_for(
    metrics: tuple[MetricObservation, ...],
    gates: tuple[GateResult, ...],
    regressions: tuple[RegressionResult, ...],
    findings: tuple[QualityFinding, ...],
) -> str:
    payload = {
        "findings": [finding_payload(finding) for finding in findings],
        "gates": [gate_result_payload(result) for result in gates],
        "metrics": [observation_payload(observation) for observation in metrics],
        "regressions": [regression_result_payload(result) for result in regressions],
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def quality_report_id_for(
    suite_id: str,
    processor: QualityProcessorDescriptor,
    policy: QualityPolicy,
    baseline_report_id: str | None,
    content_fingerprint: str,
) -> str:
    if not is_quality_suite_id(suite_id):
        raise ValueError("suite_id must be canonical")
    payload = {
        "baseline_report_id": baseline_report_id,
        "content_fingerprint": content_fingerprint,
        "policy": policy_payload(policy),
        "processor": processor_payload(processor),
        "schema_version": QUALITY_SCHEMA_VERSION,
        "suite_id": suite_id,
        "type": "pagetrace_quality_report",
    }
    return f"quality-report-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def quality_report_status_for(
    gates: tuple[GateResult, ...], regressions: tuple[RegressionResult, ...]
) -> QualityReportStatus:
    results = tuple(result.status for result in gates) + tuple(
        result.status for result in regressions
    )
    if any(status is EvaluationStatus.FAILED for status in results):
        return QualityReportStatus.FAILED
    if any(status is EvaluationStatus.NOT_EVALUATED for status in results):
        return QualityReportStatus.INCOMPLETE
    if results:
        return QualityReportStatus.PASSED
    return QualityReportStatus.OBSERVATIONAL


def compare_metric(value: float, comparator: MetricComparator, threshold: float) -> bool:
    if comparator is MetricComparator.AT_LEAST:
        return value >= threshold
    return value <= threshold


def metric_direction(metric: QualityMetricName) -> int:
    """Return 1 for higher-is-better, -1 for lower-is-better, or 0 for informational."""

    if metric in _HIGHER_IS_BETTER:
        return 1
    if metric in _LOWER_IS_BETTER:
        return -1
    return 0


def metric_degradation(
    metric: QualityMetricName, current_value: float, baseline_value: float
) -> float:
    direction = metric_direction(metric)
    if direction == 0:
        raise ValueError("informational metrics do not define degradation")
    return round((baseline_value - current_value) * direction, 12)


def metric_bounds(metric: QualityMetricName) -> tuple[float, float | None]:
    if metric in _RATE_METRICS:
        return (0.0, 1.0)
    if metric in _HUMAN_METRICS:
        return (1.0, 5.0)
    return (0.0, None)


def processor_payload(processor: QualityProcessorDescriptor) -> dict[str, object]:
    return {"name": processor.name, "version": processor.version}


def text_case_payload(case: TextQualityCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "character_error_rate": float(case.character_error_rate),
        "exact_match": case.exact_match,
        "word_error_rate": float(case.word_error_rate),
    }


def answer_case_payload(case: AnswerQualityCase) -> dict[str, object]:
    return {
        "acceptable_answers": list(case.acceptable_answers),
        "case_id": case.case_id,
        "expected_status": case.expected_status.value,
        "relevant_chunk_ids": list(case.relevant_chunk_ids),
        "result": json.loads(serialize_qa_result(case.result)),
    }


def human_review_payload(review: HumanReview) -> dict[str, object]:
    return {
        "case_id": review.case_id,
        "completeness": review.completeness,
        "correctness": review.correctness,
        "relevance": review.relevance,
        "review_id": review.review_id,
        "rubric_version": review.rubric_version,
        "traceability": review.traceability,
    }


def policy_payload(policy: QualityPolicy) -> dict[str, object]:
    return {
        "gates": [gate_payload(gate) for gate in policy.gates],
        "policy_id": policy.policy_id,
        "regression_rules": [regression_rule_payload(rule) for rule in policy.regression_rules],
    }


def gate_payload(gate: MetricGate) -> dict[str, object]:
    return {
        "comparator": gate.comparator.value,
        "metric": gate.metric.value,
        "minimum_samples": gate.minimum_samples,
        "threshold": float(gate.threshold),
    }


def regression_rule_payload(rule: RegressionRule) -> dict[str, object]:
    return {
        "maximum_degradation": float(rule.maximum_degradation),
        "metric": rule.metric.value,
        "minimum_samples": rule.minimum_samples,
    }


def observation_payload(observation: MetricObservation) -> dict[str, object]:
    return {
        "metric": observation.metric.value,
        "sample_count": observation.sample_count,
        "value": float(observation.value),
    }


def gate_result_payload(result: GateResult) -> dict[str, object]:
    return {
        "gate": gate_payload(result.gate),
        "observed_value": result.observed_value,
        "sample_count": result.sample_count,
        "status": result.status.value,
    }


def regression_result_payload(result: RegressionResult) -> dict[str, object]:
    return {
        "baseline_samples": result.baseline_samples,
        "baseline_value": result.baseline_value,
        "current_samples": result.current_samples,
        "current_value": result.current_value,
        "degradation": result.degradation,
        "rule": regression_rule_payload(result.rule),
        "status": result.status.value,
    }


def finding_payload(finding: QualityFinding) -> dict[str, object]:
    return {
        "case_id": finding.case_id,
        "code": finding.code,
        "dimension": finding.dimension.value,
        "message": finding.message,
        "severity": finding.severity.value,
    }


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _validate_safe_id(value: str, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe 1-128 character identifier")


def _validate_finite_number(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _validate_nonnegative_number(value: float, name: str) -> None:
    _validate_finite_number(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_minimum_samples(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("minimum_samples must be a positive integer")


_RATE_METRICS = {
    QualityMetricName.TEXT_EXACT_MATCH_RATE,
    QualityMetricName.RETRIEVAL_MEAN_RECIPROCAL_RANK,
    QualityMetricName.RETRIEVAL_MEAN_PRECISION,
    QualityMetricName.RETRIEVAL_MEAN_RECALL,
    QualityMetricName.RETRIEVAL_MEAN_AVERAGE_PRECISION,
    QualityMetricName.RETRIEVAL_MEAN_NDCG,
    QualityMetricName.ANSWER_STATUS_ACCURACY,
    QualityMetricName.ANSWER_EXACT_MATCH_RATE,
    QualityMetricName.PROVENANCE_CITATION_PRECISION,
    QualityMetricName.PROVENANCE_CITATION_RECALL,
    QualityMetricName.PROVENANCE_SUPPORTED_ANSWER_RATE,
    QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
}
_HUMAN_METRICS = {
    QualityMetricName.HUMAN_RELEVANCE,
    QualityMetricName.HUMAN_CORRECTNESS,
    QualityMetricName.HUMAN_COMPLETENESS,
    QualityMetricName.HUMAN_TRACEABILITY,
}
_HIGHER_IS_BETTER = {
    QualityMetricName.TEXT_EXACT_MATCH_RATE,
    QualityMetricName.RETRIEVAL_MEAN_RECIPROCAL_RANK,
    QualityMetricName.RETRIEVAL_MEAN_PRECISION,
    QualityMetricName.RETRIEVAL_MEAN_RECALL,
    QualityMetricName.RETRIEVAL_MEAN_AVERAGE_PRECISION,
    QualityMetricName.RETRIEVAL_MEAN_NDCG,
    QualityMetricName.ANSWER_STATUS_ACCURACY,
    QualityMetricName.ANSWER_EXACT_MATCH_RATE,
    QualityMetricName.PROVENANCE_CITATION_PRECISION,
    QualityMetricName.PROVENANCE_CITATION_RECALL,
    QualityMetricName.PROVENANCE_SUPPORTED_ANSWER_RATE,
    *_HUMAN_METRICS,
}
_LOWER_IS_BETTER = {
    QualityMetricName.TEXT_MEAN_CHARACTER_ERROR_RATE,
    QualityMetricName.TEXT_MEAN_WORD_ERROR_RATE,
    QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
    QualityMetricName.COST_EXTERNAL_REQUESTS,
    QualityMetricName.COST_ESTIMATED_EXTERNAL_USD,
}

DEFAULT_QUALITY_POLICY = QualityPolicy()
