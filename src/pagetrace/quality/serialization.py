"""Strict canonical JSON for quality suites and reports."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.qa import QaIntegrityError, QaStatus, deserialize_qa_result
from pagetrace.quality.errors import QualityIntegrityError
from pagetrace.quality.models import (
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
    QualityMetricName,
    QualityPolicy,
    QualityProcessorDescriptor,
    QualityReport,
    QualityReportStatus,
    QualitySuite,
    RegressionResult,
    RegressionRule,
    TextQualityCase,
    answer_case_payload,
    finding_payload,
    gate_result_payload,
    human_review_payload,
    observation_payload,
    policy_payload,
    processor_payload,
    regression_result_payload,
    text_case_payload,
)
from pagetrace.retrieval import (
    RetrievalIntegrityError,
    deserialize_retrieval_evaluation,
    serialize_retrieval_evaluation,
)

_SUITE_FIELDS = {
    "schema_version",
    "suite_id",
    "text_cases",
    "retrieval_evaluations",
    "answer_cases",
    "human_reviews",
    "policy",
}
_REPORT_FIELDS = {
    "schema_version",
    "report_id",
    "suite_id",
    "processor",
    "policy",
    "baseline_report_id",
    "status",
    "metrics",
    "gates",
    "regressions",
    "findings",
    "content_fingerprint",
}
_TEXT_CASE_FIELDS = {"case_id", "exact_match", "character_error_rate", "word_error_rate"}
_ANSWER_CASE_FIELDS = {
    "case_id",
    "result",
    "expected_status",
    "acceptable_answers",
    "relevant_chunk_ids",
}
_HUMAN_REVIEW_FIELDS = {
    "review_id",
    "case_id",
    "rubric_version",
    "relevance",
    "correctness",
    "completeness",
    "traceability",
}
_POLICY_FIELDS = {"policy_id", "gates", "regression_rules"}
_GATE_FIELDS = {"metric", "comparator", "threshold", "minimum_samples"}
_RULE_FIELDS = {"metric", "maximum_degradation", "minimum_samples"}
_PROCESSOR_FIELDS = {"name", "version"}
_OBSERVATION_FIELDS = {"metric", "value", "sample_count"}
_GATE_RESULT_FIELDS = {"gate", "status", "observed_value", "sample_count"}
_REGRESSION_RESULT_FIELDS = {
    "rule",
    "status",
    "current_value",
    "baseline_value",
    "degradation",
    "current_samples",
    "baseline_samples",
}
_FINDING_FIELDS = {"code", "severity", "dimension", "case_id", "message"}


def serialize_quality_suite(suite: QualitySuite) -> bytes:
    """Serialize a validated quality suite as canonical UTF-8 JSON."""

    return _encode(
        {
            "answer_cases": [answer_case_payload(case) for case in suite.answer_cases],
            "human_reviews": [human_review_payload(review) for review in suite.human_reviews],
            "policy": policy_payload(suite.policy),
            "retrieval_evaluations": [
                json.loads(serialize_retrieval_evaluation(evaluation))
                for evaluation in suite.retrieval_evaluations
            ],
            "schema_version": suite.schema_version,
            "suite_id": suite.suite_id,
            "text_cases": [text_case_payload(case) for case in suite.text_cases],
        }
    )


def deserialize_quality_suite(data: bytes) -> QualitySuite:
    """Parse and validate strict quality-suite JSON."""

    value = _decode(data, "quality suite")
    suite = _mapping(value, "quality suite")
    _exact(suite, _SUITE_FIELDS, "quality suite")
    try:
        retrieval_evaluations = tuple(
            deserialize_retrieval_evaluation(_encode(dict(_mapping(item, "retrieval evaluation"))))
            for item in _array(suite["retrieval_evaluations"], "retrieval_evaluations")
        )
        return QualitySuite(
            schema_version=_integer(suite["schema_version"], "schema_version"),
            suite_id=_string(suite["suite_id"], "suite_id"),
            text_cases=tuple(
                _parse_text_case(item) for item in _array(suite["text_cases"], "text_cases")
            ),
            retrieval_evaluations=retrieval_evaluations,
            answer_cases=tuple(
                _parse_answer_case(item) for item in _array(suite["answer_cases"], "answer_cases")
            ),
            human_reviews=tuple(
                _parse_human_review(item)
                for item in _array(suite["human_reviews"], "human_reviews")
            ),
            policy=_parse_policy(suite["policy"]),
        )
    except QualityIntegrityError:
        raise
    except (QaIntegrityError, RetrievalIntegrityError) as exc:
        raise QualityIntegrityError(f"invalid nested quality input: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise QualityIntegrityError(f"invalid quality suite value: {exc}") from exc


def serialize_quality_report(report: QualityReport) -> bytes:
    """Serialize a validated quality report as canonical UTF-8 JSON."""

    return _encode(
        {
            "baseline_report_id": report.baseline_report_id,
            "content_fingerprint": report.content_fingerprint,
            "findings": [finding_payload(finding) for finding in report.findings],
            "gates": [gate_result_payload(result) for result in report.gates],
            "metrics": [observation_payload(observation) for observation in report.metrics],
            "policy": policy_payload(report.policy),
            "processor": processor_payload(report.processor),
            "regressions": [regression_result_payload(result) for result in report.regressions],
            "report_id": report.report_id,
            "schema_version": report.schema_version,
            "status": report.status.value,
            "suite_id": report.suite_id,
        }
    )


def deserialize_quality_report(data: bytes) -> QualityReport:
    """Parse and validate strict quality-report JSON."""

    value = _decode(data, "quality report")
    report = _mapping(value, "quality report")
    _exact(report, _REPORT_FIELDS, "quality report")
    try:
        baseline_value = report["baseline_report_id"]
        processor = _mapping(report["processor"], "processor")
        _exact(processor, _PROCESSOR_FIELDS, "processor")
        return QualityReport(
            schema_version=_integer(report["schema_version"], "schema_version"),
            report_id=_string(report["report_id"], "report_id"),
            suite_id=_string(report["suite_id"], "suite_id"),
            processor=QualityProcessorDescriptor(
                name=_string(processor["name"], "processor.name"),
                version=_string(processor["version"], "processor.version"),
            ),
            policy=_parse_policy(report["policy"]),
            baseline_report_id=(
                None if baseline_value is None else _string(baseline_value, "baseline_report_id")
            ),
            status=QualityReportStatus(_string(report["status"], "status")),
            metrics=tuple(
                _parse_observation(item) for item in _array(report["metrics"], "metrics")
            ),
            gates=tuple(_parse_gate_result(item) for item in _array(report["gates"], "gates")),
            regressions=tuple(
                _parse_regression_result(item)
                for item in _array(report["regressions"], "regressions")
            ),
            findings=tuple(_parse_finding(item) for item in _array(report["findings"], "findings")),
            content_fingerprint=_string(report["content_fingerprint"], "content_fingerprint"),
        )
    except QualityIntegrityError:
        raise
    except (TypeError, ValueError) as exc:
        raise QualityIntegrityError(f"invalid quality report value: {exc}") from exc


def _parse_text_case(value: object) -> TextQualityCase:
    case = _mapping(value, "text case")
    _exact(case, _TEXT_CASE_FIELDS, "text case")
    return TextQualityCase(
        case_id=_string(case["case_id"], "text case_id"),
        exact_match=_boolean(case["exact_match"], "exact_match"),
        character_error_rate=_number(case["character_error_rate"], "character_error_rate"),
        word_error_rate=_number(case["word_error_rate"], "word_error_rate"),
    )


def _parse_answer_case(value: object) -> AnswerQualityCase:
    case = _mapping(value, "answer case")
    _exact(case, _ANSWER_CASE_FIELDS, "answer case")
    result = deserialize_qa_result(_encode(dict(_mapping(case["result"], "QA result"))))
    return AnswerQualityCase(
        case_id=_string(case["case_id"], "answer case_id"),
        result=result,
        expected_status=QaStatus(_string(case["expected_status"], "expected_status")),
        acceptable_answers=tuple(
            _string(item, "acceptable answer")
            for item in _array(case["acceptable_answers"], "acceptable_answers")
        ),
        relevant_chunk_ids=tuple(
            _string(item, "relevant chunk ID")
            for item in _array(case["relevant_chunk_ids"], "relevant_chunk_ids")
        ),
    )


def _parse_human_review(value: object) -> HumanReview:
    review = _mapping(value, "human review")
    _exact(review, _HUMAN_REVIEW_FIELDS, "human review")
    return HumanReview(
        review_id=_string(review["review_id"], "review_id"),
        case_id=_string(review["case_id"], "human review case_id"),
        rubric_version=_string(review["rubric_version"], "rubric_version"),
        relevance=_integer(review["relevance"], "relevance"),
        correctness=_integer(review["correctness"], "correctness"),
        completeness=_integer(review["completeness"], "completeness"),
        traceability=_integer(review["traceability"], "traceability"),
    )


def _parse_policy(value: object) -> QualityPolicy:
    policy = _mapping(value, "policy")
    _exact(policy, _POLICY_FIELDS, "policy")
    return QualityPolicy(
        policy_id=_string(policy["policy_id"], "policy_id"),
        gates=tuple(_parse_gate(item) for item in _array(policy["gates"], "gates")),
        regression_rules=tuple(
            _parse_regression_rule(item)
            for item in _array(policy["regression_rules"], "regression_rules")
        ),
    )


def _parse_gate(value: object) -> MetricGate:
    gate = _mapping(value, "gate")
    _exact(gate, _GATE_FIELDS, "gate")
    return MetricGate(
        metric=QualityMetricName(_string(gate["metric"], "gate.metric")),
        comparator=MetricComparator(_string(gate["comparator"], "gate.comparator")),
        threshold=_number(gate["threshold"], "gate.threshold"),
        minimum_samples=_integer(gate["minimum_samples"], "gate.minimum_samples"),
    )


def _parse_regression_rule(value: object) -> RegressionRule:
    rule = _mapping(value, "regression rule")
    _exact(rule, _RULE_FIELDS, "regression rule")
    return RegressionRule(
        metric=QualityMetricName(_string(rule["metric"], "regression metric")),
        maximum_degradation=_number(rule["maximum_degradation"], "maximum_degradation"),
        minimum_samples=_integer(rule["minimum_samples"], "regression minimum_samples"),
    )


def _parse_observation(value: object) -> MetricObservation:
    observation = _mapping(value, "metric observation")
    _exact(observation, _OBSERVATION_FIELDS, "metric observation")
    return MetricObservation(
        metric=QualityMetricName(_string(observation["metric"], "observation.metric")),
        value=_number(observation["value"], "observation.value"),
        sample_count=_integer(observation["sample_count"], "observation.sample_count"),
    )


def _parse_gate_result(value: object) -> GateResult:
    result = _mapping(value, "gate result")
    _exact(result, _GATE_RESULT_FIELDS, "gate result")
    observed = result["observed_value"]
    return GateResult(
        gate=_parse_gate(result["gate"]),
        status=EvaluationStatus(_string(result["status"], "gate status")),
        observed_value=None if observed is None else _number(observed, "observed_value"),
        sample_count=_integer(result["sample_count"], "gate sample_count"),
    )


def _parse_regression_result(value: object) -> RegressionResult:
    result = _mapping(value, "regression result")
    _exact(result, _REGRESSION_RESULT_FIELDS, "regression result")
    return RegressionResult(
        rule=_parse_regression_rule(result["rule"]),
        status=EvaluationStatus(_string(result["status"], "regression status")),
        current_value=_optional_number(result["current_value"], "current_value"),
        baseline_value=_optional_number(result["baseline_value"], "baseline_value"),
        degradation=_optional_number(result["degradation"], "degradation"),
        current_samples=_integer(result["current_samples"], "current_samples"),
        baseline_samples=_integer(result["baseline_samples"], "baseline_samples"),
    )


def _parse_finding(value: object) -> QualityFinding:
    finding = _mapping(value, "finding")
    _exact(finding, _FINDING_FIELDS, "finding")
    case_value = finding["case_id"]
    return QualityFinding(
        code=_string(finding["code"], "finding code"),
        severity=FindingSeverity(_string(finding["severity"], "finding severity")),
        dimension=QualityDimension(_string(finding["dimension"], "finding dimension")),
        case_id=None if case_value is None else _string(case_value, "finding case_id"),
        message=_string(finding["message"], "finding message"),
    )


def _decode(data: bytes, name: str) -> object:
    if not isinstance(data, bytes):
        raise QualityIntegrityError(f"{name} must be bytes")
    try:
        return json.loads(
            data.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid numeric constant: {value}")
            ),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QualityIntegrityError(f"{name} is not valid strict UTF-8 JSON") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QualityIntegrityError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise QualityIntegrityError(f"{name} must be an array")
    return cast(list[object], value)


def _exact(value: Mapping[str, object], fields: set[str], name: str) -> None:
    if set(value) != fields:
        raise QualityIntegrityError(f"{name} fields do not match schema")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
