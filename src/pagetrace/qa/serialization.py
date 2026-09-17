"""Strict canonical JSON for evidence-grounded QA results."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.qa.errors import QaIntegrityError
from pagetrace.qa.models import (
    AbstentionReason,
    EvidenceCitation,
    QaConfig,
    QaProcessorDescriptor,
    QaResult,
    QaStatus,
    citation_payload,
    configuration_payload,
    processor_payload,
)
from pagetrace.retrieval import (
    RetrievalIntegrityError,
    deserialize_retrieval_result,
    serialize_retrieval_result,
)

_RESULT_FIELDS = {
    "schema_version",
    "answer_id",
    "processor",
    "configuration",
    "status",
    "abstention_reason",
    "answer",
    "answer_fingerprint",
    "content_fingerprint",
    "retrieval",
    "citations",
}
_PROCESSOR_FIELDS = {
    "name",
    "version",
    "sentence_segmenter_name",
    "sentence_segmenter_version",
}
_CONFIG_FIELDS = {
    "max_evidence_items",
    "max_answer_characters",
    "minimum_query_term_coverage",
    "evidence_separator",
}
_CITATION_FIELDS = {
    "citation_index",
    "retrieval_rank",
    "chunk_id",
    "excerpt_start",
    "excerpt_end",
    "excerpt",
    "excerpt_fingerprint",
    "matched_terms",
    "query_term_coverage",
}


def serialize_qa_result(result: QaResult) -> bytes:
    """Serialize a validated QA result as canonical UTF-8 JSON."""

    retrieval_payload = json.loads(serialize_retrieval_result(result.retrieval))
    return _encode(
        {
            "abstention_reason": (
                result.abstention_reason.value if result.abstention_reason is not None else None
            ),
            "answer": result.answer,
            "answer_fingerprint": result.answer_fingerprint,
            "answer_id": result.answer_id,
            "citations": [citation_payload(citation) for citation in result.citations],
            "configuration": configuration_payload(result.configuration),
            "content_fingerprint": result.content_fingerprint,
            "processor": processor_payload(result.processor),
            "retrieval": retrieval_payload,
            "schema_version": result.schema_version,
            "status": result.status.value,
        }
    )


def deserialize_qa_result(data: bytes) -> QaResult:
    """Parse and validate strict evidence-grounded QA JSON."""

    value = _decode(data)
    result = _mapping(value, "QA result")
    _exact(result, _RESULT_FIELDS, "QA result")
    try:
        processor_value = _mapping(result["processor"], "processor")
        _exact(processor_value, _PROCESSOR_FIELDS, "processor")
        configuration_value = _mapping(result["configuration"], "configuration")
        _exact(configuration_value, _CONFIG_FIELDS, "configuration")
        retrieval_value = _mapping(result["retrieval"], "retrieval")
        retrieval = deserialize_retrieval_result(_encode(dict(retrieval_value)))
        citations = tuple(
            _parse_citation(item) for item in _array(result["citations"], "citations")
        )
        reason_value = result["abstention_reason"]
        reason = (
            None
            if reason_value is None
            else AbstentionReason(_string(reason_value, "abstention_reason"))
        )
        answer_value = result["answer"]
        answer_fingerprint_value = result["answer_fingerprint"]
        return QaResult(
            schema_version=_integer(result["schema_version"], "schema_version"),
            answer_id=_string(result["answer_id"], "answer_id"),
            processor=QaProcessorDescriptor(
                name=_string(processor_value["name"], "processor.name"),
                version=_string(processor_value["version"], "processor.version"),
                sentence_segmenter_name=_string(
                    processor_value["sentence_segmenter_name"],
                    "processor.sentence_segmenter_name",
                ),
                sentence_segmenter_version=_string(
                    processor_value["sentence_segmenter_version"],
                    "processor.sentence_segmenter_version",
                ),
            ),
            configuration=QaConfig(
                max_evidence_items=_integer(
                    configuration_value["max_evidence_items"], "max_evidence_items"
                ),
                max_answer_characters=_integer(
                    configuration_value["max_answer_characters"], "max_answer_characters"
                ),
                minimum_query_term_coverage=_number(
                    configuration_value["minimum_query_term_coverage"],
                    "minimum_query_term_coverage",
                ),
                evidence_separator=_string(
                    configuration_value["evidence_separator"], "evidence_separator"
                ),
            ),
            status=QaStatus(_string(result["status"], "status")),
            abstention_reason=reason,
            answer=None if answer_value is None else _string(answer_value, "answer"),
            answer_fingerprint=(
                None
                if answer_fingerprint_value is None
                else _string(answer_fingerprint_value, "answer_fingerprint")
            ),
            content_fingerprint=_string(result["content_fingerprint"], "content_fingerprint"),
            retrieval=retrieval,
            citations=citations,
        )
    except QaIntegrityError:
        raise
    except RetrievalIntegrityError as exc:
        raise QaIntegrityError(f"invalid source retrieval result: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise QaIntegrityError(f"invalid QA result value: {exc}") from exc


def _parse_citation(value: object) -> EvidenceCitation:
    citation = _mapping(value, "citation")
    _exact(citation, _CITATION_FIELDS, "citation")
    return EvidenceCitation(
        citation_index=_integer(citation["citation_index"], "citation_index"),
        retrieval_rank=_integer(citation["retrieval_rank"], "retrieval_rank"),
        chunk_id=_string(citation["chunk_id"], "chunk_id"),
        excerpt_start=_integer(citation["excerpt_start"], "excerpt_start"),
        excerpt_end=_integer(citation["excerpt_end"], "excerpt_end"),
        excerpt=_string(citation["excerpt"], "excerpt"),
        excerpt_fingerprint=_string(citation["excerpt_fingerprint"], "excerpt_fingerprint"),
        matched_terms=tuple(
            _string(item, "matched term")
            for item in _array(citation["matched_terms"], "matched_terms")
        ),
        query_term_coverage=_number(citation["query_term_coverage"], "query_term_coverage"),
    )


def _decode(data: bytes) -> object:
    if not isinstance(data, bytes):
        raise QaIntegrityError("QA result must be bytes")
    try:
        return json.loads(
            data.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid numeric constant: {value}")
            ),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QaIntegrityError("QA result is not valid strict UTF-8 JSON") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QaIntegrityError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise QaIntegrityError(f"{name} must be an array")
    return cast(list[object], value)


def _exact(value: Mapping[str, object], fields: set[str], name: str) -> None:
    if set(value) != fields:
        raise QaIntegrityError(f"{name} fields do not match schema")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
