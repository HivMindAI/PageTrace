"""Operator CLI for the durable PageTrace product backend."""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pagetrace.backend.errors import BackendError
from pagetrace.backend.http import create_http_server
from pagetrace.backend.models import DEFAULT_BACKEND_LIMITS
from pagetrace.backend.service import BackendService, BackgroundWorker
from pagetrace.backend.store import SqliteJobStore
from pagetrace.backend.workflows import workflow_handlers
from pagetrace.web import default_web_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pagetrace-backend", description="PageTrace durable product backend"
    )
    parser.add_argument("--database", type=Path, default=Path(".pagetrace/backend.sqlite3"))
    parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    parser.add_argument("--input-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--max-retained-jobs",
        type=_retained_job_limit,
        default=DEFAULT_BACKEND_LIMITS.max_retained_jobs,
        help="maximum durable jobs retained before new submissions are rejected",
    )
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize and verify backend persistence")

    worker = subparsers.add_parser("worker", help="run durable workflow jobs")
    worker.add_argument("--once", action="store_true", help="process at most one queued job")
    worker.add_argument("--poll-interval", type=_poll_interval, default=0.25)

    purge = subparsers.add_parser(
        "purge", help="preview or permanently delete old terminal jobs and their events"
    )
    cutoff = purge.add_mutually_exclusive_group(required=True)
    cutoff.add_argument(
        "--finished-before",
        type=_utc_timestamp,
        help="delete jobs finished before this timezone-aware RFC 3339 timestamp",
    )
    cutoff.add_argument(
        "--older-than-hours",
        type=_retention_hours,
        help="delete jobs finished more than this many hours ago",
    )
    purge.add_argument("--limit", type=_purge_limit, default=1_000)
    purge.add_argument(
        "--confirm",
        action="store_true",
        help="perform permanent deletion; without this flag only a preview is shown",
    )

    serve = subparsers.add_parser(
        "serve", help="serve the web app and authenticated loopback JSON API"
    )
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1", "localhost"))
    serve.add_argument("--port", type=_port, default=8765)
    serve.add_argument(
        "--token-env",
        default="PAGETRACE_BACKEND_TOKEN",
        help="environment variable containing the bearer token",
    )
    serve.add_argument("--no-worker", action="store_true")
    serve.add_argument(
        "--web-root",
        type=Path,
        default=default_web_root(),
        help="directory containing the built PageTrace web application",
    )
    serve.add_argument("--poll-interval", type=_poll_interval, default=0.25)
    serve.add_argument("--connection-timeout", type=_connection_timeout, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if arguments.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
        if arguments.command == "purge":
            store = _store(arguments)
            store.initialize()
            return _purge(store, arguments)
        service = _service(arguments)
        recover_interrupted = arguments.command == "worker" or (
            arguments.command == "serve" and not arguments.no_worker
        )
        service.initialize(recover_interrupted=recover_interrupted)
        if arguments.command == "init":
            print("PageTrace backend database is ready")
            return 0
        if arguments.command == "worker":
            return _run_worker(service, once=arguments.once, poll_interval=arguments.poll_interval)
        return _serve(service, arguments)
    except (BackendError, OSError, ValueError) as exc:
        print(f"pagetrace-backend: error: {exc}", file=sys.stderr)
        return 2


def _service(arguments: argparse.Namespace) -> BackendService:
    store = _store(arguments)
    handlers = workflow_handlers(
        artifact_store=arguments.store,
        allowed_input_root=arguments.input_root,
    )
    return BackendService(store, handlers)


def _store(arguments: argparse.Namespace) -> SqliteJobStore:
    limits = replace(DEFAULT_BACKEND_LIMITS, max_retained_jobs=arguments.max_retained_jobs)
    return SqliteJobStore(arguments.database, limits=limits)


def _run_worker(service: BackendService, *, once: bool, poll_interval: float) -> int:
    if once:
        service.run_until_idle(maximum_jobs=1)
        return 0
    worker = BackgroundWorker(service, poll_interval_seconds=poll_interval)
    worker.start()
    stop = threading.Event()
    try:
        while not stop.wait(86_400):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        stopped = worker.stop(timeout_seconds=30.0)
    if not stopped:
        print("pagetrace-backend: worker did not stop cleanly", file=sys.stderr)
        return 1
    return 0


def _serve(service: BackendService, arguments: argparse.Namespace) -> int:
    token = os.environ.get(arguments.token_env)
    if token is None:
        raise ValueError(f"bearer token environment variable is not set: {arguments.token_env}")
    server = create_http_server(
        service,
        host=arguments.host,
        port=arguments.port,
        bearer_token=token,
        web_root=arguments.web_root,
        connection_timeout_seconds=arguments.connection_timeout,
    )
    worker = None
    if not arguments.no_worker:
        worker = BackgroundWorker(service, poll_interval_seconds=arguments.poll_interval)
        worker.start()
    worker_stopped = True
    try:
        print(f"PageTrace web app listening on http://{arguments.host}:{server.server_port}")
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if worker is not None:
            worker_stopped = worker.stop(timeout_seconds=30.0)
    if not worker_stopped:
        print("pagetrace-backend: worker did not stop cleanly", file=sys.stderr)
        return 1
    return 0


def _purge(store: SqliteJobStore, arguments: argparse.Namespace) -> int:
    cutoff = arguments.finished_before
    if cutoff is None:
        cutoff = datetime.now(UTC) - timedelta(hours=arguments.older_than_hours)
    canonical_cutoff = cutoff.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if arguments.confirm:
        count = store.purge_terminal_jobs(finished_before=cutoff, limit=arguments.limit)
        print(f"Purged {count} terminal job(s) finished before {canonical_cutoff}")
    else:
        count = store.preview_terminal_job_purge(finished_before=cutoff, limit=arguments.limit)
        print(
            f"Purge preview: {count} terminal job(s) finished before {canonical_cutoff}; "
            "rerun with --confirm to delete"
        )
    return 0


def _poll_interval(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("poll interval must be from 0.01 through 60") from exc
    if not 0.01 <= parsed <= 60:
        raise argparse.ArgumentTypeError("poll interval must be from 0.01 through 60")
    return parsed


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 0 to 65535") from exc
    if not 0 <= parsed <= 65_535:
        raise argparse.ArgumentTypeError("port must be an integer from 0 to 65535")
    return parsed


def _retained_job_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "retained job limit must be from 1 through 1000000"
        ) from exc
    if not 1 <= parsed <= 1_000_000:
        raise argparse.ArgumentTypeError("retained job limit must be from 1 through 1000000")
    return parsed


def _purge_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("purge limit must be from 1 through 10000") from exc
    if not 1 <= parsed <= 10_000:
        raise argparse.ArgumentTypeError("purge limit must be from 1 through 10000")
    return parsed


def _retention_hours(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "retention hours must be from 0.01 through 876000"
        ) from exc
    if not math.isfinite(parsed) or not 0.01 <= parsed <= 876_000:
        raise argparse.ArgumentTypeError("retention hours must be from 0.01 through 876000")
    return parsed


def _connection_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("connection timeout must be from 0.1 through 300") from exc
    if not math.isfinite(parsed) or not 0.1 <= parsed <= 300:
        raise argparse.ArgumentTypeError("connection timeout must be from 0.1 through 300")
    return parsed


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "finished-before must be a timezone-aware RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "finished-before must be a timezone-aware RFC 3339 timestamp"
        )
    return parsed.astimezone(UTC)
