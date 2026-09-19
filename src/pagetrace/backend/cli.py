"""Operator CLI for the durable PageTrace product backend."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from pagetrace.backend.errors import BackendError
from pagetrace.backend.http import create_http_server
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
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize and verify backend persistence")

    worker = subparsers.add_parser("worker", help="run durable workflow jobs")
    worker.add_argument("--once", action="store_true", help="process at most one queued job")
    worker.add_argument("--poll-interval", type=_poll_interval, default=0.25)

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if arguments.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
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
    store = SqliteJobStore(arguments.database)
    handlers = workflow_handlers(
        artifact_store=arguments.store,
        allowed_input_root=arguments.input_root,
    )
    return BackendService(store, handlers)


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
