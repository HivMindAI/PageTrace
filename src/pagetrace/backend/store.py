"""SQLite-backed durable job queue with explicit lifecycle transitions."""

from __future__ import annotations

import sqlite3
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pagetrace.backend.errors import (
    BackendCapacityError,
    BackendConflictError,
    BackendInputError,
    BackendNotFoundError,
    BackendPersistenceError,
)
from pagetrace.backend.models import (
    BACKEND_SCHEMA_VERSION,
    DEFAULT_BACKEND_LIMITS,
    BackendEvent,
    BackendLimits,
    BackendMetrics,
    JobEventType,
    JobStatus,
    StoredJob,
    WorkflowName,
    canonical_json,
    is_job_id,
    request_fingerprint_for,
    validate_error,
    validate_idempotency_key,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

_SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    workflow TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json BLOB NOT NULL,
    request_fingerprint TEXT NOT NULL,
    result_json BLOB,
    error_code TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    cancellation_requested INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX jobs_queue_order ON jobs(status, created_at, job_id);
CREATE TABLE events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail_json BLOB NOT NULL
);
CREATE INDEX events_job_order ON events(job_id, sequence);
"""
_JOB_COLUMNS = frozenset(
    {
        "job_id",
        "idempotency_key",
        "workflow",
        "status",
        "request_json",
        "request_fingerprint",
        "result_json",
        "error_code",
        "error_message",
        "attempts",
        "max_attempts",
        "cancellation_requested",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
)
_EVENT_COLUMNS = frozenset({"sequence", "job_id", "event_type", "occurred_at", "detail_json"})


class SqliteJobStore:
    """Persistent bounded queue using one short SQLite transaction per operation."""

    def __init__(
        self,
        path: Path,
        *,
        limits: BackendLimits = DEFAULT_BACKEND_LIMITS,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        self._path = path
        self._limits = limits
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: f"job-{uuid.uuid4().hex}")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def limits(self) -> BackendLimits:
        return self._limits

    def initialize(self) -> None:
        """Create or validate the on-disk schema without silently migrating it."""

        self._prepare_path()
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = FULL")
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
                ).fetchone()
                if version == 0 and table_exists is None:
                    connection.executescript(_SCHEMA)
                    connection.execute(f"PRAGMA user_version = {BACKEND_SCHEMA_VERSION}")
                elif version != BACKEND_SCHEMA_VERSION:
                    raise BackendPersistenceError("backend database schema is unsupported")
                self._validate_schema(connection)
        except BackendPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("backend database could not be initialized") from exc

    def health_check(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version != BACKEND_SCHEMA_VERSION:
                    raise BackendPersistenceError("backend database schema is unsupported")
                self._validate_schema(connection)
        except BackendPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("backend database health check failed") from exc

    def submit(
        self,
        workflow: WorkflowName,
        request: dict[str, object],
        *,
        idempotency_key: str,
        max_attempts: int | None = None,
    ) -> tuple[StoredJob, bool]:
        """Durably submit a job, returning the existing job on an exact replay."""

        if not isinstance(workflow, WorkflowName):
            raise BackendInputError("workflow is not supported")
        try:
            validate_idempotency_key(idempotency_key)
            request_json = canonical_json(request)
        except ValueError as exc:
            raise BackendInputError(str(exc)) from exc
        if not isinstance(request, dict):
            raise BackendInputError("request must be a JSON object")
        if len(request_json) > self._limits.max_request_bytes:
            raise BackendInputError("request exceeds the configured size limit")
        attempts_limit = self._limits.max_attempts if max_attempts is None else max_attempts
        if (
            isinstance(attempts_limit, bool)
            or not isinstance(attempts_limit, int)
            or not 1 <= attempts_limit <= self._limits.max_attempts
        ):
            raise BackendInputError("max_attempts is outside the configured range")
        fingerprint = request_fingerprint_for(workflow, request_json)

        try:
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    job = _job_from_row(existing)
                    if job.request_fingerprint != fingerprint:
                        raise BackendConflictError(
                            "idempotency key was already used for a different request"
                        )
                    return job, False
                queued = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE status = ?", (JobStatus.QUEUED.value,)
                    ).fetchone()[0]
                )
                if queued >= self._limits.max_queued_jobs:
                    raise BackendCapacityError("backend job queue is at capacity")
                job_id = self._id_factory()
                if not is_job_id(job_id):
                    raise BackendPersistenceError("job identifier generator returned invalid data")
                now = self._timestamp()
                connection.execute(
                    """
                    INSERT INTO jobs (
                        job_id, idempotency_key, workflow, status, request_json,
                        request_fingerprint, result_json, error_code, error_message,
                        attempts, max_attempts, cancellation_requested, created_at,
                        updated_at, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, 0, ?, ?, NULL, NULL)
                    """,
                    (
                        job_id,
                        idempotency_key,
                        workflow.value,
                        JobStatus.QUEUED.value,
                        request_json,
                        fingerprint,
                        attempts_limit,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    job_id,
                    JobEventType.SUBMITTED,
                    now,
                    {"workflow": workflow.value},
                )
                return self._get(connection, job_id), True
        except (BackendCapacityError, BackendConflictError, BackendPersistenceError):
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job could not be submitted") from exc

    def get(self, job_id: str) -> StoredJob:
        self._validate_job_id(job_id)
        try:
            with self._connect() as connection:
                return self._get(connection, job_id)
        except BackendNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job could not be read") from exc

    def claim_next(self) -> StoredJob | None:
        """Atomically claim the oldest queued job for one worker."""

        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT job_id FROM jobs
                    WHERE status = ?
                    ORDER BY created_at, job_id
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value,),
                ).fetchone()
                if row is None:
                    return None
                job_id = str(row["job_id"])
                now = self._timestamp()
                updated = connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, attempts = attempts + 1, cancellation_requested = 0,
                        updated_at = ?, started_at = ?, finished_at = NULL,
                        result_json = NULL, error_code = NULL, error_message = NULL
                    WHERE job_id = ? AND status = ?
                    """,
                    (
                        JobStatus.RUNNING.value,
                        now,
                        now,
                        job_id,
                        JobStatus.QUEUED.value,
                    ),
                ).rowcount
                if updated != 1:
                    raise BackendPersistenceError("queued job could not be claimed atomically")
                job = self._get(connection, job_id)
                self._append_event(
                    connection,
                    job_id,
                    JobEventType.STARTED,
                    now,
                    {"attempt": job.attempts},
                )
                return job
        except BackendPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("next job could not be claimed") from exc

    def complete(self, job_id: str, result: object) -> StoredJob:
        self._validate_job_id(job_id)
        try:
            result_json = canonical_json(result)
        except ValueError as exc:
            raise BackendInputError("workflow result is not valid JSON") from exc
        if len(result_json) > self._limits.max_result_bytes:
            raise BackendCapacityError("workflow result exceeds the configured size limit")
        try:
            with self._transaction() as connection:
                current = self._get(connection, job_id)
                if current.status is not JobStatus.RUNNING:
                    raise BackendConflictError("only running jobs can be completed")
                now = self._timestamp()
                if current.cancellation_requested:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, cancellation_requested = 0,
                            updated_at = ?, finished_at = ?, result_json = NULL
                        WHERE job_id = ?
                        """,
                        (JobStatus.CANCELLED.value, now, now, job_id),
                    )
                    self._append_event(
                        connection, job_id, JobEventType.CANCELLED, now, {"phase": "running"}
                    )
                else:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?,
                            result_json = ?, error_code = NULL, error_message = NULL
                        WHERE job_id = ?
                        """,
                        (JobStatus.SUCCEEDED.value, now, now, result_json, job_id),
                    )
                    self._append_event(
                        connection,
                        job_id,
                        JobEventType.SUCCEEDED,
                        now,
                        {"attempt": current.attempts},
                    )
                return self._get(connection, job_id)
        except (BackendConflictError, BackendNotFoundError):
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job completion could not be persisted") from exc

    def fail(self, job_id: str, code: str, message: str) -> StoredJob:
        self._validate_job_id(job_id)
        try:
            validate_error(code, message, max_characters=self._limits.max_error_characters)
        except ValueError as exc:
            raise BackendInputError(str(exc)) from exc
        try:
            with self._transaction() as connection:
                current = self._get(connection, job_id)
                if current.status is not JobStatus.RUNNING:
                    raise BackendConflictError("only running jobs can fail")
                now = self._timestamp()
                if current.cancellation_requested:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, cancellation_requested = 0,
                            updated_at = ?, finished_at = ?, error_code = NULL,
                            error_message = NULL
                        WHERE job_id = ?
                        """,
                        (JobStatus.CANCELLED.value, now, now, job_id),
                    )
                    event_type = JobEventType.CANCELLED
                    detail: dict[str, object] = {"phase": "running"}
                elif current.attempts < current.max_attempts:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, updated_at = ?, started_at = NULL,
                            finished_at = NULL, error_code = NULL, error_message = NULL
                        WHERE job_id = ?
                        """,
                        (JobStatus.QUEUED.value, now, job_id),
                    )
                    event_type = JobEventType.RETRY_QUEUED
                    detail = {"attempt": current.attempts, "error_code": code}
                else:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?,
                            error_code = ?, error_message = ?
                        WHERE job_id = ?
                        """,
                        (JobStatus.FAILED.value, now, now, code, message, job_id),
                    )
                    event_type = JobEventType.FAILED
                    detail = {"attempt": current.attempts, "error_code": code}
                self._append_event(connection, job_id, event_type, now, detail)
                return self._get(connection, job_id)
        except (BackendConflictError, BackendNotFoundError):
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job failure could not be persisted") from exc

    def request_cancel(self, job_id: str) -> StoredJob:
        """Cancel a queued job or signal cooperative cancellation for a running job."""

        self._validate_job_id(job_id)
        try:
            with self._transaction() as connection:
                current = self._get(connection, job_id)
                if current.status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                }:
                    return current
                if current.cancellation_requested:
                    return current
                now = self._timestamp()
                if current.status is JobStatus.QUEUED:
                    connection.execute(
                        """
                        UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?,
                            cancellation_requested = 0
                        WHERE job_id = ?
                        """,
                        (JobStatus.CANCELLED.value, now, now, job_id),
                    )
                    event_type = JobEventType.CANCELLED
                    detail: dict[str, object] = {"phase": "queued"}
                else:
                    connection.execute(
                        """
                        UPDATE jobs SET cancellation_requested = 1, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (now, job_id),
                    )
                    event_type = JobEventType.CANCELLATION_REQUESTED
                    detail = {"phase": "running"}
                self._append_event(connection, job_id, event_type, now, detail)
                return self._get(connection, job_id)
        except BackendNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job cancellation could not be persisted") from exc

    def list_events(
        self, job_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[BackendEvent, ...]:
        self._validate_job_id(job_id)
        if (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise BackendInputError("after_sequence must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise BackendInputError("event limit must be an integer from 1 to 1000")
        try:
            with self._connect() as connection:
                self._get(connection, job_id)
                rows = connection.execute(
                    """
                    SELECT * FROM events
                    WHERE job_id = ? AND sequence > ?
                    ORDER BY sequence
                    LIMIT ?
                    """,
                    (job_id, after_sequence, limit),
                ).fetchall()
            return tuple(_event_from_row(row) for row in rows)
        except BackendNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise BackendPersistenceError("job events could not be read") from exc

    def metrics(self) -> BackendMetrics:
        try:
            with self._connect() as connection:
                counts = {
                    str(row["status"]): int(row["count"])
                    for row in connection.execute(
                        "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
                    ).fetchall()
                }
                total_events = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            return BackendMetrics(
                queued=counts.get(JobStatus.QUEUED.value, 0),
                running=counts.get(JobStatus.RUNNING.value, 0),
                succeeded=counts.get(JobStatus.SUCCEEDED.value, 0),
                failed=counts.get(JobStatus.FAILED.value, 0),
                cancelled=counts.get(JobStatus.CANCELLED.value, 0),
                total_events=total_events,
            )
        except sqlite3.Error as exc:
            raise BackendPersistenceError("backend metrics could not be read") from exc

    def recover_interrupted_jobs(self) -> tuple[StoredJob, ...]:
        """Move jobs left running by a stopped process into retry or terminal state."""

        recovered: list[StoredJob] = []
        try:
            with self._transaction() as connection:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at, job_id",
                    (JobStatus.RUNNING.value,),
                ).fetchall()
                for row in rows:
                    current = _job_from_row(row)
                    now = self._timestamp()
                    if current.cancellation_requested:
                        connection.execute(
                            """
                            UPDATE jobs SET status = ?, cancellation_requested = 0,
                                updated_at = ?, finished_at = ?
                            WHERE job_id = ?
                            """,
                            (JobStatus.CANCELLED.value, now, now, current.job_id),
                        )
                        event_type = JobEventType.CANCELLED
                        detail: dict[str, object] = {"phase": "recovery"}
                    elif current.attempts < current.max_attempts:
                        connection.execute(
                            """
                            UPDATE jobs SET status = ?, updated_at = ?, started_at = NULL,
                                finished_at = NULL
                            WHERE job_id = ?
                            """,
                            (JobStatus.QUEUED.value, now, current.job_id),
                        )
                        event_type = JobEventType.RECOVERED
                        detail = {"attempt": current.attempts, "outcome": "requeued"}
                    else:
                        connection.execute(
                            """
                            UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?,
                                error_code = ?, error_message = ?
                            WHERE job_id = ?
                            """,
                            (
                                JobStatus.FAILED.value,
                                now,
                                now,
                                "worker_interrupted",
                                "worker stopped before the workflow completed",
                                current.job_id,
                            ),
                        )
                        event_type = JobEventType.FAILED
                        detail = {"attempt": current.attempts, "error_code": "worker_interrupted"}
                    self._append_event(connection, current.job_id, event_type, now, detail)
                    recovered.append(self._get(connection, current.job_id))
            return tuple(recovered)
        except sqlite3.Error as exc:
            raise BackendPersistenceError("interrupted jobs could not be recovered") from exc

    def _prepare_path(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists() or self._path.is_symlink():
                metadata = self._path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise BackendPersistenceError(
                        "backend database must be a regular non-symlink file"
                    )
        except BackendPersistenceError:
            raise
        except OSError as exc:
            raise BackendPersistenceError("backend database path could not be prepared") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _get(self, connection: sqlite3.Connection, job_id: str) -> StoredJob:
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise BackendNotFoundError("job was not found")
        try:
            return _job_from_row(row)
        except (TypeError, ValueError, KeyError, sqlite3.Error) as exc:
            raise BackendPersistenceError("stored job data is invalid") from exc

    def _append_event(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        event_type: JobEventType,
        occurred_at: str,
        detail: dict[str, object],
    ) -> None:
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
        )
        if count >= self._limits.max_events_per_job:
            raise BackendPersistenceError("job event limit was reached")
        connection.execute(
            "INSERT INTO events (job_id, event_type, occurred_at, detail_json) VALUES (?, ?, ?, ?)",
            (job_id, event_type.value, occurred_at, canonical_json(detail)),
        )

    def _timestamp(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise BackendPersistenceError("backend clock must return an aware datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _validate_job_id(self, job_id: str) -> None:
        if not is_job_id(job_id):
            raise BackendInputError("job identifier is invalid")

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not {"jobs", "events"}.issubset(tables):
            raise BackendPersistenceError("backend database schema is incomplete")
        job_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        event_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(events)").fetchall()
        }
        if job_columns != _JOB_COLUMNS or event_columns != _EVENT_COLUMNS:
            raise BackendPersistenceError("backend database schema is incompatible")


def _job_from_row(row: sqlite3.Row) -> StoredJob:
    return StoredJob(
        job_id=str(row["job_id"]),
        idempotency_key=str(row["idempotency_key"]),
        workflow=WorkflowName(str(row["workflow"])),
        status=JobStatus(str(row["status"])),
        request_json=bytes(row["request_json"]),
        request_fingerprint=str(row["request_fingerprint"]),
        result_json=bytes(row["result_json"]) if row["result_json"] is not None else None,
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=str(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
    )


def _event_from_row(row: sqlite3.Row) -> BackendEvent:
    return BackendEvent(
        sequence=int(row["sequence"]),
        job_id=str(row["job_id"]),
        event_type=JobEventType(str(row["event_type"])),
        occurred_at=str(row["occurred_at"]),
        detail_json=bytes(row["detail_json"]),
    )
