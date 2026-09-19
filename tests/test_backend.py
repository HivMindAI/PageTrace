from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

import pagetrace.backend.workflows as backend_workflows
from pagetrace.backend import (
    BackendCapacityError,
    BackendConfigurationError,
    BackendConflictError,
    BackendEvent,
    BackendInputError,
    BackendLimits,
    BackendMetrics,
    BackendNotFoundError,
    BackendPersistenceError,
    BackendService,
    BackgroundWorker,
    BuiltinWorkflowHandlers,
    JobEventType,
    JobStatus,
    SqliteJobStore,
    WorkflowFailure,
    WorkflowName,
    event_public_payload,
    job_public_payload,
    metrics_payload,
)
from pagetrace.backend.models import (
    canonical_json,
    finite_number,
    parse_canonical_json,
    request_fingerprint_for,
    validate_error,
    validate_timestamp,
)
from pagetrace.qa import answer_from_retrieval
from pagetrace.quality import serialize_quality_suite
from tests.conftest import ImageFactory
from tests.test_qa import _retrieve
from tests.test_quality import _full_suite


@pytest.fixture
def job_ids() -> Iterator[str]:
    return (f"job-{number:032x}" for number in range(1, 100))


@pytest.fixture
def store(tmp_path: Path, job_ids: Iterator[str]) -> SqliteJobStore:
    result = SqliteJobStore(
        tmp_path / "backend.sqlite3",
        clock=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        id_factory=lambda: next(job_ids),
    )
    result.initialize()
    return result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_request_bytes", 0),
        ("max_result_bytes", -1),
        ("max_queued_jobs", True),
        ("max_retained_jobs", 0),
        ("max_attempts", 0),
        ("max_error_characters", 0),
        ("max_events_per_job", 0),
    ],
)
def test_backend_limits_reject_non_positive_values(field: str, value: object) -> None:
    values: dict[str, Any] = {
        "max_request_bytes": 1,
        "max_result_bytes": 1,
        "max_queued_jobs": 1,
        "max_retained_jobs": 1,
        "max_attempts": 1,
        "max_error_characters": 1,
        "max_events_per_job": 1,
    }
    values[field] = value
    with pytest.raises(ValueError, match="positive integer"):
        BackendLimits(**values)


def test_backend_store_enables_connection_security_pragmas(store: SqliteJobStore) -> None:
    with store._connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_canonical_json_boundary_is_strict() -> None:
    encoded = canonical_json({"z": [1, True, None], "a": "é"})
    assert encoded == '{"a":"é","z":[1,true,null]}'.encode()
    assert parse_canonical_json(encoded, "value") == {"a": "é", "z": [1, True, None]}

    for invalid in (b'{"a":1, "b":2}', b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"):
        with pytest.raises(ValueError, match="JSON"):
            parse_canonical_json(invalid, "value")
    with pytest.raises(ValueError, match="finite JSON-compatible"):
        canonical_json(float("inf"))
    with pytest.raises(ValueError, match="finite JSON-compatible"):
        canonical_json(object())
    with pytest.raises(ValueError, match="finite number"):
        finite_number(True)
    with pytest.raises(ValueError, match="UTC offset"):
        validate_timestamp("2026-01-01")
    with pytest.raises(ValueError, match="safe lowercase identifier"):
        validate_error("BAD", "message", max_characters=20)
    with pytest.raises(ValueError, match="error message"):
        validate_error("valid", "", max_characters=20)
    with pytest.raises(ValueError, match="WorkflowName"):
        request_fingerprint_for(cast(WorkflowName, "bad"), b"{}")
    assert finite_number(2) == 2.0


def test_backend_persistent_models_reject_contradictions(store: SqliteJobStore) -> None:
    queued, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="models")
    invalid_jobs: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: replace(queued, job_id="bad"), "job_id"),
        (lambda: replace(queued, workflow=cast(WorkflowName, "bad")), "backend enums"),
        (lambda: replace(queued, request_json=b"[]"), "JSON object"),
        (lambda: replace(queued, request_fingerprint="0" * 64), "fingerprint"),
        (lambda: replace(queued, result_json=b"not-json"), "strict UTF-8 JSON"),
        (lambda: replace(queued, error_code="BAD"), "safe lowercase"),
        (lambda: replace(queued, error_message=""), "must not be empty"),
        (lambda: replace(queued, attempts=cast(int, True)), "non-negative integer"),
        (lambda: replace(queued, max_attempts=0), "attempt counters"),
        (lambda: replace(queued, cancellation_requested=cast(bool, 1)), "boolean"),
        (lambda: replace(queued, finished_at=queued.created_at), "queued jobs"),
        (
            lambda: replace(queued, status=JobStatus.RUNNING, started_at=None),
            "running job",
        ),
        (
            lambda: replace(queued, status=JobStatus.SUCCEEDED, finished_at=queued.created_at),
            "succeeded jobs",
        ),
        (
            lambda: replace(
                queued,
                status=JobStatus.FAILED,
                error_code="failed",
                error_message="failed",
                finished_at=None,
            ),
            "failed jobs",
        ),
        (
            lambda: replace(
                queued,
                status=JobStatus.FAILED,
                error_code="failed",
                error_message="failed",
                finished_at=queued.created_at,
                result_json=b"{}",
            ),
            "cannot contain a result",
        ),
        (lambda: replace(queued, status=JobStatus.CANCELLED), "cancelled jobs"),
    )
    for create_invalid, message in invalid_jobs:
        with pytest.raises(ValueError, match=message):
            create_invalid()

    event = store.list_events(queued.job_id)[0]
    invalid_events: tuple[Callable[[], object], ...] = (
        lambda: replace(event, sequence=0),
        lambda: replace(event, job_id="bad"),
        lambda: replace(event, event_type=cast(JobEventType, "bad")),
        lambda: replace(event, detail_json=b"[]"),
    )
    for create_invalid in invalid_events:
        with pytest.raises(ValueError, match=r"event|JSON object"):
            create_invalid()

    metrics = store.metrics()
    with pytest.raises(ValueError, match="non-negative integer"):
        replace(metrics, queued=-1)
    assert BackendMetrics(0, 0, 0, 0, 0, 0).total_events == 0
    assert isinstance(event, BackendEvent)


def test_store_submit_replay_complete_events_and_metrics(store: SqliteJobStore) -> None:
    job, created = store.submit(
        WorkflowName.INGEST_DOCUMENT,
        {"source_path": "sample.pdf"},
        idempotency_key="request-1",
    )
    replay, replay_created = store.submit(
        WorkflowName.INGEST_DOCUMENT,
        {"source_path": "sample.pdf"},
        idempotency_key="request-1",
    )

    assert created is True
    assert replay_created is False
    assert replay == job == store.get(job.job_id)
    assert job.status is JobStatus.QUEUED
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempts == 1
    completed = store.complete(job.job_id, {"document_id": "document-sha256-test"})
    assert completed.status is JobStatus.SUCCEEDED
    assert job_public_payload(completed)["result"] == {"document_id": "document-sha256-test"}
    events = store.list_events(job.job_id)
    assert [event.event_type for event in events] == [
        JobEventType.SUBMITTED,
        JobEventType.STARTED,
        JobEventType.SUCCEEDED,
    ]
    assert event_public_payload(events[0])["detail"] == {"workflow": "ingest_document"}
    assert metrics_payload(store.metrics()) == {
        "cancelled": 0,
        "failed": 0,
        "queued": 0,
        "running": 0,
        "succeeded": 1,
        "total_events": 3,
    }
    assert store.claim_next() is None
    store.health_check()


def test_store_enforces_submission_and_query_boundaries(tmp_path: Path) -> None:
    ids = (f"job-{number:032x}" for number in range(1, 10))
    store = SqliteJobStore(
        tmp_path / "bounded.sqlite3",
        limits=BackendLimits(max_request_bytes=20, max_queued_jobs=1, max_attempts=2),
        id_factory=lambda: next(ids),
    )
    store.initialize()
    first, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="same")

    with pytest.raises(BackendConflictError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {"x": 1}, idempotency_key="same")
    with pytest.raises(BackendCapacityError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="second")
    with pytest.raises(BackendInputError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {"long": "x" * 30}, idempotency_key="large")
    with pytest.raises(BackendInputError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="bad key")
    with pytest.raises(BackendInputError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="attempts", max_attempts=3)
    with pytest.raises(BackendInputError):
        store.get("unsafe")
    with pytest.raises(BackendNotFoundError):
        store.get("job-00000000000000000000000000000099")
    with pytest.raises(BackendInputError):
        store.list_events(first.job_id, after_sequence=-1)
    with pytest.raises(BackendInputError):
        store.list_events(first.job_id, limit=0)


def test_store_caps_retained_jobs_but_allows_idempotent_replay(tmp_path: Path) -> None:
    ids = (f"job-{number:032x}" for number in range(1, 5))
    store = SqliteJobStore(
        tmp_path / "retained.sqlite3",
        limits=BackendLimits(max_queued_jobs=4, max_retained_jobs=1),
        id_factory=lambda: next(ids),
    )
    store.initialize()
    first, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="first")

    replay, created = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="first")
    assert replay == first
    assert created is False
    with pytest.raises(BackendCapacityError, match="retained job limit"):
        store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="second")


def test_store_previews_and_purges_only_old_terminal_jobs(tmp_path: Path) -> None:
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    ids = (f"job-{number:032x}" for number in range(1, 6))
    store = SqliteJobStore(
        tmp_path / "purge.sqlite3",
        clock=lambda: current[0],
        id_factory=lambda: next(ids),
    )
    store.initialize()

    oldest, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="oldest")
    store.claim_next()
    store.complete(oldest.job_id, {"sensitive": "oldest"})

    current[0] = datetime(2026, 1, 1, 12, tzinfo=UTC)
    old, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="old")
    store.claim_next()
    store.complete(old.job_id, {"sensitive": "old"})

    current[0] = datetime(2026, 1, 3, tzinfo=UTC)
    recent, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="recent")
    store.claim_next()
    store.complete(recent.job_id, {"sensitive": "recent"})
    queued, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="queued")

    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    assert store.preview_terminal_job_purge(finished_before=cutoff) == 2
    assert store.preview_terminal_job_purge(finished_before=cutoff, limit=1) == 1
    assert store.purge_terminal_jobs(finished_before=cutoff, limit=1) == 1
    with pytest.raises(BackendNotFoundError):
        store.get(oldest.job_id)
    assert store.get(old.job_id).status is JobStatus.SUCCEEDED
    assert store.get(recent.job_id).status is JobStatus.SUCCEEDED
    assert store.get(queued.job_id).status is JobStatus.QUEUED
    assert store.purge_terminal_jobs(finished_before=cutoff) == 1
    with pytest.raises(BackendNotFoundError):
        store.get(old.job_id)
    assert store.metrics().total_events == 4
    assert store.purge_terminal_jobs(finished_before=cutoff) == 0

    with pytest.raises(BackendInputError, match="timezone-aware"):
        store.preview_terminal_job_purge(finished_before=datetime(2026, 1, 2))
    with pytest.raises(BackendInputError, match="purge limit"):
        store.purge_terminal_jobs(finished_before=cutoff, limit=0)


def test_store_retries_cancellation_and_recovery(tmp_path: Path) -> None:
    ids = (f"job-{number:032x}" for number in range(1, 20))
    store = SqliteJobStore(
        tmp_path / "lifecycle.sqlite3",
        limits=BackendLimits(max_attempts=2),
        id_factory=lambda: next(ids),
    )
    store.initialize()
    retry, _ = store.submit(
        WorkflowName.ANSWER_QUESTION, {}, idempotency_key="retry", max_attempts=2
    )
    store.claim_next()
    requeued = store.fail(retry.job_id, "temporary_failure", "try again")
    assert requeued.status is JobStatus.QUEUED
    assert requeued.started_at is None
    store.claim_next()
    failed = store.fail(retry.job_id, "temporary_failure", "try again")
    assert failed.status is JobStatus.FAILED
    assert job_public_payload(failed)["error"] == {
        "code": "temporary_failure",
        "message": "try again",
    }

    queued, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="queued")
    assert store.request_cancel(queued.job_id).status is JobStatus.CANCELLED
    assert store.request_cancel(queued.job_id).status is JobStatus.CANCELLED

    running, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="running")
    store.claim_next()
    assert store.request_cancel(running.job_id).cancellation_requested is True
    assert store.complete(running.job_id, {"ignored": True}).status is JobStatus.CANCELLED

    recover, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="recover")
    store.claim_next()
    recovered = store.recover_interrupted_jobs()
    assert [job.job_id for job in recovered] == [recover.job_id]
    assert recovered[0].status is JobStatus.QUEUED
    store.claim_next()
    store.complete(recover.job_id, {})

    exhausted, _ = store.submit(
        WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="exhausted", max_attempts=1
    )
    store.claim_next()
    terminal = store.recover_interrupted_jobs()
    assert terminal[0].job_id == exhausted.job_id
    assert terminal[0].error_code == "worker_interrupted"


def test_store_rejects_invalid_transitions_and_storage(tmp_path: Path) -> None:
    ids = iter(("invalid", "job-00000000000000000000000000000002"))
    store = SqliteJobStore(tmp_path / "invalid.sqlite3", id_factory=lambda: next(ids))
    store.initialize()
    with pytest.raises(BackendPersistenceError):
        store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="id")

    valid, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="valid")
    with pytest.raises(BackendConflictError):
        store.complete(valid.job_id, {})
    with pytest.raises(BackendConflictError):
        store.fail(valid.job_id, "failure", "failed")
    store.claim_next()
    with pytest.raises(BackendInputError):
        store.complete(valid.job_id, object())
    with pytest.raises(BackendInputError):
        store.fail(valid.job_id, "BAD", "failed")
    bounded = SqliteJobStore(
        tmp_path / "result-limit.sqlite3",
        limits=BackendLimits(max_result_bytes=2),
    )
    bounded.initialize()
    bounded_job, _ = bounded.submit(
        WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="bounded", max_attempts=1
    )
    bounded.claim_next()
    with pytest.raises(BackendCapacityError, match="result exceeds"):
        bounded.complete(bounded_job.job_id, {"x": 1})

    directory_db = tmp_path / "directory-db"
    directory_db.mkdir()
    with pytest.raises(BackendPersistenceError):
        SqliteJobStore(directory_db).initialize()

    unsupported = tmp_path / "unsupported.sqlite3"
    with sqlite3.connect(unsupported) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(BackendPersistenceError):
        SqliteJobStore(unsupported).initialize()

    incomplete = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(incomplete) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(BackendPersistenceError, match="incomplete"):
        SqliteJobStore(incomplete).initialize()

    incompatible = tmp_path / "incompatible.sqlite3"
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE jobs (job_id TEXT)")
        connection.execute("CREATE TABLE events (sequence INTEGER)")
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(BackendPersistenceError, match="incompatible"):
        SqliteJobStore(incompatible).initialize()

    with pytest.raises(TypeError, match=r"pathlib\.Path"):
        SqliteJobStore(cast(Path, "bad"))
    assert store.path == tmp_path / "invalid.sqlite3"
    assert store.limits.max_attempts == 3


def test_store_cancelled_failure_recovery_event_limit_and_corruption(tmp_path: Path) -> None:
    ids = (f"job-{number:032x}" for number in range(1, 10))
    store = SqliteJobStore(tmp_path / "extra.sqlite3", id_factory=lambda: next(ids))
    store.initialize()
    cancelled, _ = store.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="cancel-fail")
    store.claim_next()
    store.request_cancel(cancelled.job_id)
    assert store.fail(cancelled.job_id, "failed", "failed").status is JobStatus.CANCELLED

    recovering, _ = store.submit(
        WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="cancel-recover"
    )
    store.claim_next()
    store.request_cancel(recovering.job_id)
    recovered = store.recover_interrupted_jobs()
    assert recovered[0].status is JobStatus.CANCELLED

    event_store = SqliteJobStore(
        tmp_path / "events.sqlite3",
        limits=BackendLimits(max_events_per_job=1),
    )
    event_store.initialize()
    event_job, _ = event_store.submit(
        WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="event-limit"
    )
    with pytest.raises(BackendPersistenceError, match="event limit"):
        event_store.claim_next()
    assert event_store.get(event_job.job_id).status is JobStatus.QUEUED

    corrupt_store = SqliteJobStore(tmp_path / "corrupt.sqlite3")
    corrupt_store.initialize()
    corrupt_job, _ = corrupt_store.submit(
        WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="corrupt"
    )
    with sqlite3.connect(corrupt_store.path) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'unknown' WHERE job_id = ?", (corrupt_job.job_id,)
        )
    with pytest.raises(BackendPersistenceError, match="stored job data"):
        corrupt_store.get(corrupt_job.job_id)

    naive_clock = SqliteJobStore(tmp_path / "clock.sqlite3", clock=lambda: datetime(2026, 1, 1))
    naive_clock.initialize()
    with pytest.raises(BackendPersistenceError, match="aware datetime"):
        naive_clock.submit(WorkflowName.EVALUATE_QUALITY, {}, idempotency_key="clock")


def test_service_runs_safe_outcomes_and_observer(tmp_path: Path) -> None:
    ids = (f"job-{number:032x}" for number in range(1, 20))
    store = SqliteJobStore(
        tmp_path / "service.sqlite3",
        limits=BackendLimits(max_attempts=1, max_result_bytes=20),
        id_factory=lambda: next(ids),
    )
    observed: list[str] = []

    def handler(request: dict[str, object]) -> object:
        behavior = request["behavior"]
        if behavior == "safe-failure":
            raise WorkflowFailure("input_rejected", "input was rejected")
        if behavior == "invalid-failure":
            raise WorkflowFailure("BAD", "invalid handler failure")
        if behavior == "exception":
            raise RuntimeError("secret details")
        if behavior == "large":
            return {"value": "x" * 100}
        return {"ok": True}

    service = BackendService(
        store,
        {WorkflowName.EVALUATE_QUALITY: handler},
        observer=lambda event, fields: observed.append(event),
    )
    assert service.initialize() == ()
    assert service.ready() is True
    for number, behavior in enumerate(
        ("success", "safe-failure", "invalid-failure", "exception", "large"), 1
    ):
        service.submit(
            WorkflowName.EVALUATE_QUALITY,
            {"behavior": behavior},
            idempotency_key=f"service-{number}",
            max_attempts=1,
        )
    assert service.run_until_idle() == 5
    statuses = [store.get(f"job-{number:032x}").status for number in range(1, 6)]
    assert statuses == [
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.FAILED,
        JobStatus.FAILED,
        JobStatus.FAILED,
    ]
    assert store.get("job-00000000000000000000000000000004").error_message == (
        "workflow execution failed"
    )
    assert "job_submitted" in observed
    assert observed.count("job_attempt_finished") == 5
    with pytest.raises(ValueError, match="positive integer"):
        service.run_until_idle(maximum_jobs=0)


def test_service_unavailable_handler_and_background_worker(store: SqliteJobStore) -> None:
    service = BackendService(store, {})
    job, _ = service.submit(
        WorkflowName.INGEST_DOCUMENT, {}, idempotency_key="missing", max_attempts=1
    )
    result = service.run_next()
    assert result is not None
    assert result.error_code == "handler_unavailable"
    assert service.cancel(job.job_id).status is JobStatus.FAILED

    queued, _ = service.submit(WorkflowName.INGEST_DOCUMENT, {}, idempotency_key="worker")
    worker = BackgroundWorker(service, poll_interval_seconds=0.01)
    worker.start()
    with pytest.raises(RuntimeError):
        worker.start()
    deadline = time.monotonic() + 2
    while service.get(queued.job_id).status is JobStatus.QUEUED and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.stop(timeout_seconds=2) is True
    with pytest.raises(ValueError, match="non-negative number"):
        worker.stop(timeout_seconds=-1)
    with pytest.raises(ValueError, match="poll interval"):
        BackgroundWorker(service, poll_interval_seconds=0)


def test_builtin_workflow_ingestion_and_rejections(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    image_factory(inputs / "sample.png", image_format="PNG")
    handlers = BuiltinWorkflowHandlers(
        artifact_store=tmp_path / "artifacts", allowed_input_root=inputs
    )

    manifest = handlers.ingest_document({"source_path": "sample.png"})
    assert isinstance(manifest, dict)
    assert manifest["media_type"] == "image/png"
    with pytest.raises(WorkflowFailure):
        handlers.ingest_document({"source_path": str(tmp_path / "outside.png")})
    with pytest.raises(WorkflowFailure):
        handlers.ingest_document({"source_path": "sample.png", "unknown": True})
    with pytest.raises(WorkflowFailure):
        handlers.answer_question({"document_id": "invalid"})
    with pytest.raises(WorkflowFailure):
        handlers.evaluate_quality({"suite": []})

    suite = json.loads(serialize_quality_suite(_full_suite()))
    report = handlers.evaluate_quality({"suite": suite, "baseline": None})
    assert isinstance(report, dict)
    assert report["status"] == "passed"
    regression = handlers.evaluate_quality({"suite": suite, "baseline": report})
    assert isinstance(regression, dict)
    assert regression["baseline_report_id"] == report["report_id"]
    assert set(handlers.as_mapping()) == set(WorkflowName)

    qa_result = answer_from_retrieval(_retrieve((("alpha answer.",),), "alpha"))
    monkeypatch.setattr(backend_workflows, "answer_question", lambda *args, **kwargs: qa_result)
    answer = handlers.answer_question(
        {
            "corpus_artifact_id": qa_result.retrieval.source_corpus_artifact_id,
            "document_id": qa_result.retrieval.document_id,
            "max_answer_characters": 100,
            "max_evidence_items": 2,
            "minimum_query_term_coverage": 0.5,
            "question": "alpha",
            "top_k": 1,
        }
    )
    assert isinstance(answer, dict)
    assert answer["status"] == "answered"
    with pytest.raises(WorkflowFailure):
        handlers.answer_question(
            {
                "corpus_artifact_id": "corpus",
                "document_id": "document",
                "question": "question",
                "top_k": True,
            }
        )

    file_path = tmp_path / "not-directory"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(BackendConfigurationError):
        BuiltinWorkflowHandlers(artifact_store=tmp_path / "store", allowed_input_root=file_path)
    with pytest.raises(BackendConfigurationError, match="could not be prepared"):
        BuiltinWorkflowHandlers(
            artifact_store=tmp_path / "store", allowed_input_root=tmp_path / "missing"
        )
    with pytest.raises(BackendConfigurationError, match=r"pathlib\.Path"):
        BuiltinWorkflowHandlers(artifact_store=cast(Path, "bad"), allowed_input_root=inputs)
    with pytest.raises(ValueError, match="serialization is invalid"):
        backend_workflows._serialized_payload(b"{}\n\n", "test")
