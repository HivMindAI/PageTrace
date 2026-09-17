"""Strict canonical JSON for retrieval results, judgments, and evaluations."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.documents import DimensionUnit
from pagetrace.retrieval.errors import RetrievalIntegrityError
from pagetrace.retrieval.models import (
    RetrievalCaseMetrics,
    RetrievalConfig,
    RetrievalDataset,
    RetrievalEvaluation,
    RetrievalHit,
    RetrievalJudgment,
    RetrievalLimits,
    RetrievalProcessorDescriptor,
    RetrievalResult,
    case_metrics_payload,
    hit_payload,
    judgment_payload,
)
from pagetrace.structure import BoundingBox, CoordinateOrigin

_PROCESSOR_FIELDS = {
    "name",
    "version",
    "tokenizer_name",
    "tokenizer_version",
    "unicode_version",
}
_CONFIG_FIELDS = {"k1", "b", "top_k", "limits"}
_LIMIT_FIELDS = {"max_query_characters", "max_query_tokens"}
_RESULT_FIELDS = {
    "schema_version",
    "result_id",
    "document_id",
    "document_fingerprint",
    "source_corpus_artifact_id",
    "source_corpus_content_fingerprint",
    "processor",
    "configuration",
    "query",
    "query_fingerprint",
    "query_tokens",
    "corpus_chunk_count",
    "returned_hit_count",
    "content_fingerprint",
    "hits",
}
_HIT_FIELDS = {
    "rank",
    "score",
    "chunk_id",
    "chunk_index",
    "chunk_content_fingerprint",
    "page_id",
    "page_number",
    "dimension_unit",
    "coordinate_origin",
    "bounding_box",
    "text",
    "matched_terms",
}
_DATASET_FIELDS = {"schema_version", "dataset_id", "source_corpus_artifact_id", "cases"}
_JUDGMENT_FIELDS = {"query_id", "query", "relevant_chunk_ids"}
_EVALUATION_FIELDS = {
    "schema_version",
    "evaluation_id",
    "dataset_id",
    "source_corpus_artifact_id",
    "source_corpus_content_fingerprint",
    "processor",
    "configuration",
    "case_count",
    "mean_reciprocal_rank",
    "mean_precision",
    "mean_recall",
    "mean_average_precision",
    "mean_ndcg",
    "content_fingerprint",
    "cases",
}
_CASE_METRIC_FIELDS = {
    "query_id",
    "relevant_count",
    "retrieved_count",
    "relevant_retrieved_count",
    "reciprocal_rank",
    "precision",
    "recall",
    "average_precision",
    "ndcg",
}
_BOX_FIELDS = {"x0", "top", "x1", "bottom"}


def serialize_retrieval_result(result: RetrievalResult) -> bytes:
    """Serialize a validated result as canonical UTF-8 JSON."""

    payload: dict[str, object] = {
        "configuration": _configuration_payload(result.configuration),
        "content_fingerprint": result.content_fingerprint,
        "corpus_chunk_count": result.corpus_chunk_count,
        "document_fingerprint": result.document_fingerprint,
        "document_id": result.document_id,
        "hits": [hit_payload(hit) for hit in result.hits],
        "processor": _processor_payload(result.processor),
        "query": result.query,
        "query_fingerprint": result.query_fingerprint,
        "query_tokens": list(result.query_tokens),
        "result_id": result.result_id,
        "returned_hit_count": result.returned_hit_count,
        "schema_version": result.schema_version,
        "source_corpus_artifact_id": result.source_corpus_artifact_id,
        "source_corpus_content_fingerprint": result.source_corpus_content_fingerprint,
    }
    return _encode(payload)


def deserialize_retrieval_result(data: bytes) -> RetrievalResult:
    """Parse and validate strict retrieval-result JSON."""

    value = _decode(data, "retrieval result")
    result = _mapping(value, "retrieval result")
    _exact(result, _RESULT_FIELDS, "retrieval result")
    try:
        processor = _parse_processor(result["processor"])
        configuration = _parse_configuration(result["configuration"])
        hits = tuple(_parse_hit(item) for item in _array(result["hits"], "hits"))
        return RetrievalResult(
            schema_version=_integer(result["schema_version"], "schema_version"),
            result_id=_string(result["result_id"], "result_id"),
            document_id=_string(result["document_id"], "document_id"),
            document_fingerprint=_string(result["document_fingerprint"], "document_fingerprint"),
            source_corpus_artifact_id=_string(
                result["source_corpus_artifact_id"], "source_corpus_artifact_id"
            ),
            source_corpus_content_fingerprint=_string(
                result["source_corpus_content_fingerprint"],
                "source_corpus_content_fingerprint",
            ),
            processor=processor,
            configuration=configuration,
            query=_string(result["query"], "query"),
            query_fingerprint=_string(result["query_fingerprint"], "query_fingerprint"),
            query_tokens=tuple(
                _string(item, "query token")
                for item in _array(result["query_tokens"], "query_tokens")
            ),
            corpus_chunk_count=_integer(result["corpus_chunk_count"], "corpus_chunk_count"),
            returned_hit_count=_integer(result["returned_hit_count"], "returned_hit_count"),
            content_fingerprint=_string(result["content_fingerprint"], "content_fingerprint"),
            hits=hits,
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalIntegrityError(f"invalid retrieval result value: {exc}") from exc


def serialize_retrieval_dataset(dataset: RetrievalDataset) -> bytes:
    """Serialize binary relevance judgments as canonical UTF-8 JSON."""

    return _encode(
        {
            "cases": [judgment_payload(case) for case in dataset.cases],
            "dataset_id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "source_corpus_artifact_id": dataset.source_corpus_artifact_id,
        }
    )


def deserialize_retrieval_dataset(data: bytes) -> RetrievalDataset:
    """Parse and validate strict retrieval-dataset JSON."""

    value = _decode(data, "retrieval dataset")
    dataset = _mapping(value, "retrieval dataset")
    _exact(dataset, _DATASET_FIELDS, "retrieval dataset")
    try:
        cases = tuple(_parse_judgment(item) for item in _array(dataset["cases"], "cases"))
        return RetrievalDataset(
            schema_version=_integer(dataset["schema_version"], "schema_version"),
            dataset_id=_string(dataset["dataset_id"], "dataset_id"),
            source_corpus_artifact_id=_string(
                dataset["source_corpus_artifact_id"], "source_corpus_artifact_id"
            ),
            cases=cases,
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalIntegrityError(f"invalid retrieval dataset value: {exc}") from exc


def serialize_retrieval_evaluation(evaluation: RetrievalEvaluation) -> bytes:
    """Serialize retrieval metrics as canonical UTF-8 JSON."""

    return _encode(
        {
            "case_count": evaluation.case_count,
            "cases": [case_metrics_payload(case) for case in evaluation.cases],
            "configuration": _configuration_payload(evaluation.configuration),
            "content_fingerprint": evaluation.content_fingerprint,
            "dataset_id": evaluation.dataset_id,
            "evaluation_id": evaluation.evaluation_id,
            "mean_average_precision": float(evaluation.mean_average_precision),
            "mean_ndcg": float(evaluation.mean_ndcg),
            "mean_precision": float(evaluation.mean_precision),
            "mean_recall": float(evaluation.mean_recall),
            "mean_reciprocal_rank": float(evaluation.mean_reciprocal_rank),
            "processor": _processor_payload(evaluation.processor),
            "schema_version": evaluation.schema_version,
            "source_corpus_artifact_id": evaluation.source_corpus_artifact_id,
            "source_corpus_content_fingerprint": (evaluation.source_corpus_content_fingerprint),
        }
    )


def deserialize_retrieval_evaluation(data: bytes) -> RetrievalEvaluation:
    """Parse and validate strict retrieval-evaluation JSON."""

    value = _decode(data, "retrieval evaluation")
    evaluation = _mapping(value, "retrieval evaluation")
    _exact(evaluation, _EVALUATION_FIELDS, "retrieval evaluation")
    try:
        processor = _parse_processor(evaluation["processor"])
        configuration = _parse_configuration(evaluation["configuration"])
        cases = tuple(_parse_case_metrics(item) for item in _array(evaluation["cases"], "cases"))
        return RetrievalEvaluation(
            schema_version=_integer(evaluation["schema_version"], "schema_version"),
            evaluation_id=_string(evaluation["evaluation_id"], "evaluation_id"),
            dataset_id=_string(evaluation["dataset_id"], "dataset_id"),
            source_corpus_artifact_id=_string(
                evaluation["source_corpus_artifact_id"], "source_corpus_artifact_id"
            ),
            source_corpus_content_fingerprint=_string(
                evaluation["source_corpus_content_fingerprint"],
                "source_corpus_content_fingerprint",
            ),
            processor=processor,
            configuration=configuration,
            case_count=_integer(evaluation["case_count"], "case_count"),
            mean_reciprocal_rank=_number(
                evaluation["mean_reciprocal_rank"], "mean_reciprocal_rank"
            ),
            mean_precision=_number(evaluation["mean_precision"], "mean_precision"),
            mean_recall=_number(evaluation["mean_recall"], "mean_recall"),
            mean_average_precision=_number(
                evaluation["mean_average_precision"], "mean_average_precision"
            ),
            mean_ndcg=_number(evaluation["mean_ndcg"], "mean_ndcg"),
            content_fingerprint=_string(evaluation["content_fingerprint"], "content_fingerprint"),
            cases=cases,
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalIntegrityError(f"invalid retrieval evaluation value: {exc}") from exc


def _parse_processor(value: object) -> RetrievalProcessorDescriptor:
    processor = _mapping(value, "processor")
    _exact(processor, _PROCESSOR_FIELDS, "processor")
    return RetrievalProcessorDescriptor(
        name=_string(processor["name"], "processor.name"),
        version=_string(processor["version"], "processor.version"),
        tokenizer_name=_string(processor["tokenizer_name"], "processor.tokenizer_name"),
        tokenizer_version=_string(processor["tokenizer_version"], "processor.tokenizer_version"),
        unicode_version=_string(processor["unicode_version"], "processor.unicode_version"),
    )


def _parse_configuration(value: object) -> RetrievalConfig:
    configuration = _mapping(value, "configuration")
    _exact(configuration, _CONFIG_FIELDS, "configuration")
    limits_value = _mapping(configuration["limits"], "configuration.limits")
    _exact(limits_value, _LIMIT_FIELDS, "configuration.limits")
    return RetrievalConfig(
        k1=_number(configuration["k1"], "configuration.k1"),
        b=_number(configuration["b"], "configuration.b"),
        top_k=_integer(configuration["top_k"], "configuration.top_k"),
        limits=RetrievalLimits(
            max_query_characters=_integer(
                limits_value["max_query_characters"], "max_query_characters"
            ),
            max_query_tokens=_integer(limits_value["max_query_tokens"], "max_query_tokens"),
        ),
    )


def _parse_hit(value: object) -> RetrievalHit:
    hit = _mapping(value, "hit")
    _exact(hit, _HIT_FIELDS, "hit")
    return RetrievalHit(
        rank=_integer(hit["rank"], "hit.rank"),
        score=_number(hit["score"], "hit.score"),
        chunk_id=_string(hit["chunk_id"], "hit.chunk_id"),
        chunk_index=_integer(hit["chunk_index"], "hit.chunk_index"),
        chunk_content_fingerprint=_string(
            hit["chunk_content_fingerprint"], "hit.chunk_content_fingerprint"
        ),
        page_id=_string(hit["page_id"], "hit.page_id"),
        page_number=_integer(hit["page_number"], "hit.page_number"),
        dimension_unit=DimensionUnit(_string(hit["dimension_unit"], "hit.dimension_unit")),
        coordinate_origin=CoordinateOrigin(
            _string(hit["coordinate_origin"], "hit.coordinate_origin")
        ),
        bounding_box=_parse_box(hit["bounding_box"], "hit.bounding_box"),
        text=_string(hit["text"], "hit.text"),
        matched_terms=tuple(
            _string(item, "matched term")
            for item in _array(hit["matched_terms"], "hit.matched_terms")
        ),
    )


def _parse_judgment(value: object) -> RetrievalJudgment:
    judgment = _mapping(value, "judgment")
    _exact(judgment, _JUDGMENT_FIELDS, "judgment")
    return RetrievalJudgment(
        query_id=_string(judgment["query_id"], "judgment.query_id"),
        query=_string(judgment["query"], "judgment.query"),
        relevant_chunk_ids=tuple(
            _string(item, "relevant chunk ID")
            for item in _array(judgment["relevant_chunk_ids"], "judgment.relevant_chunk_ids")
        ),
    )


def _parse_case_metrics(value: object) -> RetrievalCaseMetrics:
    case = _mapping(value, "case metrics")
    _exact(case, _CASE_METRIC_FIELDS, "case metrics")
    return RetrievalCaseMetrics(
        query_id=_string(case["query_id"], "case.query_id"),
        relevant_count=_integer(case["relevant_count"], "case.relevant_count"),
        retrieved_count=_integer(case["retrieved_count"], "case.retrieved_count"),
        relevant_retrieved_count=_integer(
            case["relevant_retrieved_count"], "case.relevant_retrieved_count"
        ),
        reciprocal_rank=_number(case["reciprocal_rank"], "case.reciprocal_rank"),
        precision=_number(case["precision"], "case.precision"),
        recall=_number(case["recall"], "case.recall"),
        average_precision=_number(case["average_precision"], "case.average_precision"),
        ndcg=_number(case["ndcg"], "case.ndcg"),
    )


def _processor_payload(processor: RetrievalProcessorDescriptor) -> dict[str, object]:
    return {
        "name": processor.name,
        "tokenizer_name": processor.tokenizer_name,
        "tokenizer_version": processor.tokenizer_version,
        "unicode_version": processor.unicode_version,
        "version": processor.version,
    }


def _configuration_payload(configuration: RetrievalConfig) -> dict[str, object]:
    return {
        "b": float(configuration.b),
        "k1": float(configuration.k1),
        "limits": {
            "max_query_characters": configuration.limits.max_query_characters,
            "max_query_tokens": configuration.limits.max_query_tokens,
        },
        "top_k": configuration.top_k,
    }


def _parse_box(value: object, name: str) -> BoundingBox:
    box = _mapping(value, name)
    _exact(box, _BOX_FIELDS, name)
    return BoundingBox(
        x0=_number(box["x0"], f"{name}.x0"),
        top=_number(box["top"], f"{name}.top"),
        x1=_number(box["x1"], f"{name}.x1"),
        bottom=_number(box["bottom"], f"{name}.bottom"),
    )


def _decode(data: bytes, name: str) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetrievalIntegrityError(f"{name} is not valid UTF-8 JSON") from exc


def _encode(value: object) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RetrievalIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise RetrievalIntegrityError(f"{name} must be a JSON array")
    return value


def _exact(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RetrievalIntegrityError(
            f"{name} fields are invalid; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise RetrievalIntegrityError(f"{name} must be a string")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalIntegrityError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RetrievalIntegrityError(f"{name} must be a finite number")
    return float(value)
