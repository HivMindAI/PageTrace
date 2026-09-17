"""Stable models for persistent background workflow execution."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

BACKEND_SCHEMA_VERSION = 1
_JOB_ID_PATTERN = re.compile(r"^job-[0-9a-f]{32}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class WorkflowName(StrEnum):
    """Built-in product workflows accepted by the backend."""

    INGEST_DOCUMENT = "ingest_document"
    ANSWER_QUESTION = "answer_question"
    EVALUATE_QUALITY = "evaluate_quality"


class JobStatus(StrEnum):
    """Persistent job lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEventType(StrEnum):
    """Append-only operational event types."""

    SUBMITTED = "submitted"
    STARTED = "started"
    RETRY_QUEUED = "retry_queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    RECOVERED = "recovered"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


@dataclass(frozen=True, slots=True)
class BackendLimits:
    """Operational bounds enforced before durable acceptance."""

    max_request_bytes: int = 16 * 1024 * 1024
    max_result_bytes: int = 32 * 1024 * 1024
    max_queued_jobs: int = 1_000
    max_attempts: int = 3
    max_error_characters: int = 1_000
    max_events_per_job: int = 1_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_request_bytes", self.max_request_bytes),
            ("max_result_bytes", self.max_result_bytes),
            ("max_queued_jobs", self.max_queued_jobs),
            ("max_attempts", self.max_attempts),
            ("max_error_characters", self.max_error_characters),
            ("max_events_per_job", self.max_events_per_job),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_BACKEND_LIMITS = BackendLimits()


@dataclass(frozen=True, slots=True)
class StoredJob:
    """Immutable snapshot of one durable workflow job."""

    job_id: str
    idempotency_key: str
    workflow: WorkflowName
    status: JobStatus
    request_json: bytes
    request_fingerprint: str
    result_json: bytes | None
    error_code: str | None
    error_message: str | None
    attempts: int
    max_attempts: int
    cancellation_requested: bool
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None

    def __post_init__(self) -> None:
        if not is_job_id(self.job_id):
            raise ValueError("job_id is not canonical")
        validate_idempotency_key(self.idempotency_key)
        if not isinstance(self.workflow, WorkflowName) or not isinstance(self.status, JobStatus):
            raise ValueError("workflow and status must use backend enums")
        request = parse_canonical_json(self.request_json, "job request")
        if not isinstance(request, dict):
            raise ValueError("job request must be a JSON object")
        if self.request_fingerprint != request_fingerprint_for(self.workflow, self.request_json):
            raise ValueError("request_fingerprint does not match workflow and request")
        if self.result_json is not None:
            parse_canonical_json(self.result_json, "job result")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or _ERROR_CODE_PATTERN.fullmatch(self.error_code) is None
        ):
            raise ValueError("error_code must be a safe lowercase identifier")
        if self.error_message is not None and (
            not isinstance(self.error_message, str) or not self.error_message
        ):
            raise ValueError("error_message must not be empty")
        for name, value in (("attempts", self.attempts), ("max_attempts", self.max_attempts)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_attempts < 1 or self.attempts > self.max_attempts:
            raise ValueError("job attempt counters are inconsistent")
        if not isinstance(self.cancellation_requested, bool):
            raise ValueError("cancellation_requested must be a boolean")
        validate_timestamp(self.created_at)
        validate_timestamp(self.updated_at)
        if self.started_at is not None:
            validate_timestamp(self.started_at)
        if self.finished_at is not None:
            validate_timestamp(self.finished_at)
        self._validate_state()

    def _validate_state(self) -> None:
        if self.status is JobStatus.QUEUED:
            if self.result_json is not None or self.error_code is not None or self.finished_at:
                raise ValueError("queued jobs cannot contain terminal output")
        elif self.status is JobStatus.RUNNING:
            if (
                self.started_at is None
                or self.finished_at is not None
                or self.result_json is not None
            ):
                raise ValueError("running job timestamps or output are inconsistent")
        elif self.status is JobStatus.SUCCEEDED:
            if self.result_json is None or self.finished_at is None or self.error_code is not None:
                raise ValueError("succeeded jobs require result and finish time without an error")
        elif self.status is JobStatus.FAILED:
            if self.error_code is None or self.error_message is None or self.finished_at is None:
                raise ValueError("failed jobs require a public error and finish time")
            if self.result_json is not None:
                raise ValueError("failed jobs cannot contain a result")
        elif self.finished_at is None or self.result_json is not None:
            raise ValueError("cancelled jobs require finish time and no result")


@dataclass(frozen=True, slots=True)
class BackendEvent:
    """One ordered append-only lifecycle event."""

    sequence: int
    job_id: str
    event_type: JobEventType
    occurred_at: str
    detail_json: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("event sequence must be a positive integer")
        if not is_job_id(self.job_id):
            raise ValueError("event job_id is not canonical")
        if not isinstance(self.event_type, JobEventType):
            raise ValueError("event_type must be a JobEventType")
        validate_timestamp(self.occurred_at)
        detail = parse_canonical_json(self.detail_json, "event detail")
        if not isinstance(detail, dict):
            raise ValueError("event detail must be a JSON object")


@dataclass(frozen=True, slots=True)
class BackendMetrics:
    """Current persistent queue and outcome counters."""

    queued: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    total_events: int

    def __post_init__(self) -> None:
        for name, value in (
            ("queued", self.queued),
            ("running", self.running),
            ("succeeded", self.succeeded),
            ("failed", self.failed),
            ("cancelled", self.cancelled),
            ("total_events", self.total_events),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


def canonical_json(value: object) -> bytes:
    """Encode strict canonical JSON used at the backend trust boundary."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain only finite JSON-compatible data") from exc


def parse_canonical_json(data: bytes, name: str) -> object:
    """Decode strict UTF-8 JSON and require canonical byte representation."""

    if not isinstance(data, bytes):
        raise ValueError(f"{name} must be bytes")
    try:
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"invalid numeric constant: {item}")
            ),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} must be strict UTF-8 JSON") from exc
    if canonical_json(value) != data:
        raise ValueError(f"{name} must use canonical JSON encoding")
    return value


def request_fingerprint_for(workflow: WorkflowName, request_json: bytes) -> str:
    if not isinstance(workflow, WorkflowName):
        raise ValueError("workflow must be a WorkflowName")
    parse_canonical_json(request_json, "job request")
    return hashlib.sha256(workflow.value.encode() + b"\0" + request_json).hexdigest()


def is_job_id(value: str) -> bool:
    return isinstance(value, str) and _JOB_ID_PATTERN.fullmatch(value) is not None


def validate_idempotency_key(value: str) -> None:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("idempotency key must be a safe 1-128 character identifier")


def validate_error(code: str, message: str, *, max_characters: int) -> None:
    if not isinstance(code, str) or _ERROR_CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("error code must be a safe lowercase identifier")
    if not isinstance(message, str) or not message or len(message) > max_characters:
        raise ValueError(f"error message must contain 1 to {max_characters} characters")


def validate_timestamp(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")


def job_public_payload(job: StoredJob) -> dict[str, object]:
    """Return the stable API representation without echoing sensitive request input."""

    payload: dict[str, object] = {
        "attempts": job.attempts,
        "cancellation_requested": job.cancellation_requested,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "job_id": job.job_id,
        "max_attempts": job.max_attempts,
        "request_fingerprint": job.request_fingerprint,
        "started_at": job.started_at,
        "status": job.status.value,
        "updated_at": job.updated_at,
        "workflow": job.workflow.value,
    }
    if job.result_json is not None:
        payload["result"] = parse_canonical_json(job.result_json, "job result")
    if job.error_code is not None:
        payload["error"] = {"code": job.error_code, "message": job.error_message}
    return payload


def event_public_payload(event: BackendEvent) -> dict[str, object]:
    return {
        "detail": parse_canonical_json(event.detail_json, "event detail"),
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at,
        "sequence": event.sequence,
    }


def metrics_payload(metrics: BackendMetrics) -> dict[str, int]:
    return {
        "cancelled": metrics.cancelled,
        "failed": metrics.failed,
        "queued": metrics.queued,
        "running": metrics.running,
        "succeeded": metrics.succeeded,
        "total_events": metrics.total_events,
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def finite_number(value: object) -> float:
    """Validate a finite number for workflow configuration parsing."""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("value must be a finite number")
    return float(value)
