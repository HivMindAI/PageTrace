"""Application service and background execution for durable PageTrace workflows."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import cast

from pagetrace.backend.errors import (
    BackendCapacityError,
    BackendError,
    BackendInputError,
    WorkflowFailure,
)
from pagetrace.backend.models import (
    BackendEvent,
    BackendMetrics,
    StoredJob,
    WorkflowName,
    parse_canonical_json,
)
from pagetrace.backend.store import SqliteJobStore

WorkflowHandler = Callable[[dict[str, object]], object]
EventObserver = Callable[[str, Mapping[str, object]], None]

_LOG = logging.getLogger(__name__)


class BackendService:
    """Stable product boundary over persistence and injected workflow handlers."""

    def __init__(
        self,
        store: SqliteJobStore,
        handlers: Mapping[WorkflowName, WorkflowHandler],
        *,
        observer: EventObserver | None = None,
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._observer = observer

    @property
    def store(self) -> SqliteJobStore:
        return self._store

    def initialize(self, *, recover_interrupted: bool = True) -> tuple[StoredJob, ...]:
        self._store.initialize()
        recovered = self._store.recover_interrupted_jobs() if recover_interrupted else ()
        if recovered:
            self._observe("jobs_recovered", {"count": len(recovered)})
        return recovered

    def submit(
        self,
        workflow: WorkflowName,
        request: dict[str, object],
        *,
        idempotency_key: str,
        max_attempts: int | None = None,
    ) -> tuple[StoredJob, bool]:
        job, created = self._store.submit(
            workflow,
            request,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )
        if created:
            self._observe("job_submitted", {"job_id": job.job_id, "workflow": job.workflow.value})
        return job, created

    def get(self, job_id: str) -> StoredJob:
        return self._store.get(job_id)

    def cancel(self, job_id: str) -> StoredJob:
        job = self._store.request_cancel(job_id)
        self._observe("job_cancel_requested", {"job_id": job.job_id, "status": job.status.value})
        return job

    def events(
        self, job_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[BackendEvent, ...]:
        return self._store.list_events(job_id, after_sequence=after_sequence, limit=limit)

    def metrics(self) -> BackendMetrics:
        return self._store.metrics()

    def ready(self) -> bool:
        try:
            self._store.health_check()
        except BackendError:
            return False
        return True

    def run_next(self) -> StoredJob | None:
        """Claim and execute at most one job, persisting every outcome."""

        job = self._store.claim_next()
        if job is None:
            return None
        handler = self._handlers.get(job.workflow)
        if handler is None:
            result = self._store.fail(
                job.job_id,
                "handler_unavailable",
                "workflow handler is not available",
            )
            self._observe_outcome(result)
            return result
        request = cast(dict[str, object], parse_canonical_json(job.request_json, "job request"))
        try:
            output = handler(request)
            result = self._store.complete(job.job_id, output)
        except WorkflowFailure as exc:
            try:
                result = self._store.fail(job.job_id, exc.code, exc.message)
            except BackendInputError:
                result = self._store.fail(
                    job.job_id,
                    "workflow_failed",
                    "workflow execution failed",
                )
        except BackendCapacityError:
            result = self._store.fail(
                job.job_id,
                "result_too_large",
                "workflow result exceeds the configured size limit",
            )
        except Exception:
            _LOG.exception("workflow handler failed", extra={"job_id": job.job_id})
            result = self._store.fail(
                job.job_id,
                "workflow_failed",
                "workflow execution failed",
            )
        self._observe_outcome(result)
        return result

    def run_until_idle(self, *, maximum_jobs: int | None = None) -> int:
        if maximum_jobs is not None and (
            isinstance(maximum_jobs, bool) or not isinstance(maximum_jobs, int) or maximum_jobs < 1
        ):
            raise ValueError("maximum_jobs must be a positive integer or None")
        completed = 0
        while maximum_jobs is None or completed < maximum_jobs:
            if self.run_next() is None:
                break
            completed += 1
        return completed

    def _observe_outcome(self, job: StoredJob) -> None:
        self._observe(
            "job_attempt_finished",
            {
                "attempts": job.attempts,
                "job_id": job.job_id,
                "status": job.status.value,
                "workflow": job.workflow.value,
            },
        )

    def _observe(self, event: str, fields: Mapping[str, object]) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event, fields)
        except Exception:
            _LOG.exception("backend observer failed", extra={"event": event})


class BackgroundWorker:
    """Single-process worker loop with bounded polling and cooperative shutdown."""

    def __init__(self, service: BackendService, *, poll_interval_seconds: float = 0.25) -> None:
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0.01 <= poll_interval_seconds <= 60.0
        ):
            raise ValueError("poll interval must be from 0.01 through 60 seconds")
        self._service = service
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("background worker is already running")
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="pagetrace-backend-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout_seconds: float = 10.0) -> bool:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds < 0
        ):
            raise ValueError("timeout must be a non-negative number")
        self._stop.set()
        thread = self._thread
        if thread is None:
            return True
        thread.join(float(timeout_seconds))
        return not thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._service.run_next()
            except BackendError:
                _LOG.exception("backend worker iteration failed")
                self._stop.wait(self._poll_interval_seconds)
                continue
            if job is None:
                self._stop.wait(self._poll_interval_seconds)
