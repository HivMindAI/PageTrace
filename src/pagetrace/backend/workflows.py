"""Secure adapters from backend requests to deterministic PageTrace workflows."""

from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path

from pagetrace.backend.errors import BackendConfigurationError, WorkflowFailure
from pagetrace.backend.models import (
    WorkflowName,
    canonical_json,
    finite_number,
    parse_canonical_json,
)
from pagetrace.backend.service import WorkflowHandler
from pagetrace.documents import DocumentError, ingest_document, serialize_manifest
from pagetrace.qa import QaConfig, QaError, answer_question, serialize_qa_result
from pagetrace.quality import (
    QualityError,
    deserialize_quality_report,
    deserialize_quality_suite,
    evaluate_quality,
    serialize_quality_report,
)
from pagetrace.retrieval import RetrievalConfig, RetrievalError

_INGEST_FIELDS = frozenset({"source_path"})
_ANSWER_REQUIRED_FIELDS = frozenset({"document_id", "corpus_artifact_id", "question"})
_ANSWER_OPTIONAL_FIELDS = frozenset(
    {"top_k", "max_evidence_items", "max_answer_characters", "minimum_query_term_coverage"}
)
_QUALITY_REQUIRED_FIELDS = frozenset({"suite"})
_QUALITY_OPTIONAL_FIELDS = frozenset({"baseline"})


class BuiltinWorkflowHandlers:
    """Bound workflow handlers with fixed storage and input roots."""

    def __init__(self, *, artifact_store: Path, allowed_input_root: Path) -> None:
        self._artifact_store = _safe_directory(artifact_store, create=True, label="artifact store")
        self._allowed_input_root = _safe_directory(
            allowed_input_root, create=False, label="allowed input root"
        )

    def as_mapping(self) -> Mapping[WorkflowName, WorkflowHandler]:
        return {
            WorkflowName.INGEST_DOCUMENT: self.ingest_document,
            WorkflowName.ANSWER_QUESTION: self.answer_question,
            WorkflowName.EVALUATE_QUALITY: self.evaluate_quality,
        }

    def ingest_document(self, request: dict[str, object]) -> object:
        try:
            _require_fields(request, _INGEST_FIELDS, frozenset())
            source = _string(request, "source_path", maximum_characters=4_096)
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = self._allowed_input_root / source_path
            resolved = source_path.resolve(strict=True)
            if not resolved.is_relative_to(self._allowed_input_root):
                raise ValueError("source path is outside the allowed input root")
            metadata = source_path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("source path must be a regular non-symlink file")
            manifest = ingest_document(source_path, store=self._artifact_store)
            return _serialized_payload(serialize_manifest(manifest), "document manifest")
        except (OSError, ValueError, DocumentError) as exc:
            raise WorkflowFailure(
                "workflow_input_rejected", "document ingestion request was rejected"
            ) from exc

    def answer_question(self, request: dict[str, object]) -> object:
        try:
            _require_fields(request, _ANSWER_REQUIRED_FIELDS, _ANSWER_OPTIONAL_FIELDS)
            document_id = _string(request, "document_id", maximum_characters=256)
            corpus_artifact_id = _string(request, "corpus_artifact_id", maximum_characters=256)
            question = _string(request, "question", maximum_characters=10_000)
            top_k = _integer(request, "top_k", default=10, minimum=1, maximum=1_000)
            max_evidence = _integer(
                request, "max_evidence_items", default=3, minimum=1, maximum=100
            )
            max_answer = _integer(
                request,
                "max_answer_characters",
                default=4_000,
                minimum=1,
                maximum=100_000,
            )
            coverage = _number(
                request,
                "minimum_query_term_coverage",
                default=0.25,
                minimum_exclusive=0.0,
                maximum=1.0,
            )
            result = answer_question(
                document_id,
                corpus_artifact_id,
                question,
                store=self._artifact_store,
                retrieval_configuration=RetrievalConfig(top_k=top_k),
                configuration=QaConfig(
                    max_evidence_items=max_evidence,
                    max_answer_characters=max_answer,
                    minimum_query_term_coverage=coverage,
                ),
            )
            return _serialized_payload(serialize_qa_result(result), "QA result")
        except (ValueError, RetrievalError, QaError) as exc:
            raise WorkflowFailure(
                "workflow_input_rejected", "question-answering request was rejected"
            ) from exc

    def evaluate_quality(self, request: dict[str, object]) -> object:
        try:
            _require_fields(request, _QUALITY_REQUIRED_FIELDS, _QUALITY_OPTIONAL_FIELDS)
            suite_value = request["suite"]
            if not isinstance(suite_value, dict):
                raise ValueError("suite must be a JSON object")
            suite = deserialize_quality_suite(canonical_json(suite_value))
            baseline_value = request.get("baseline")
            if baseline_value is not None and not isinstance(baseline_value, dict):
                raise ValueError("baseline must be a JSON object or null")
            baseline = (
                deserialize_quality_report(canonical_json(baseline_value))
                if baseline_value is not None
                else None
            )
            report = evaluate_quality(suite, baseline=baseline)
            return _serialized_payload(serialize_quality_report(report), "quality report")
        except (ValueError, QualityError) as exc:
            raise WorkflowFailure(
                "workflow_input_rejected", "quality evaluation request was rejected"
            ) from exc


def _safe_directory(path: Path, *, create: bool, label: str) -> Path:
    if not isinstance(path, Path):
        raise BackendConfigurationError(f"{label} must be a pathlib.Path")
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise BackendConfigurationError(f"{label} must be a non-symlink directory")
        return path.resolve(strict=True)
    except BackendConfigurationError:
        raise
    except OSError as exc:
        raise BackendConfigurationError(f"{label} could not be prepared") from exc


def _require_fields(
    request: dict[str, object], required: frozenset[str], optional: frozenset[str]
) -> None:
    fields = frozenset(request)
    if not required.issubset(fields) or not fields.issubset(required | optional):
        raise ValueError("workflow request has missing or unknown fields")


def _string(request: dict[str, object], name: str, *, maximum_characters: int) -> str:
    value = request[name]
    if not isinstance(value, str) or not value or len(value) > maximum_characters:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _integer(
    request: dict[str, object],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = request.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside its allowed range")
    return value


def _number(
    request: dict[str, object],
    name: str,
    *,
    default: float,
    minimum_exclusive: float,
    maximum: float,
) -> float:
    value = finite_number(request.get(name, default))
    if not minimum_exclusive < value <= maximum:
        raise ValueError(f"{name} is outside its allowed range")
    return value


def _serialized_payload(data: bytes, label: str) -> object:
    if data.endswith(b"\n\n"):
        raise ValueError(f"{label} serialization is invalid")
    payload = data[:-1] if data.endswith(b"\n") else data
    return parse_canonical_json(payload, label)


def workflow_handlers(
    *, artifact_store: Path, allowed_input_root: Path
) -> Mapping[WorkflowName, WorkflowHandler]:
    """Build all built-in handlers with immutable filesystem boundaries."""

    return BuiltinWorkflowHandlers(
        artifact_store=artifact_store, allowed_input_root=allowed_input_root
    ).as_mapping()
