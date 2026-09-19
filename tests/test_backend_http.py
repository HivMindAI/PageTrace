from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from pagetrace.backend import (
    BackendError,
    BackendLimits,
    BackendPersistenceError,
    BackendService,
    JobStatus,
    SqliteJobStore,
    WorkflowName,
    create_http_server,
)

_TOKEN = "test-token-with-at-least-thirty-two-characters"


@pytest.fixture
def backend_server(tmp_path: Path) -> Iterator[tuple[ThreadingHTTPServer, BackendService]]:
    store = SqliteJobStore(tmp_path / "http.sqlite3")
    service = BackendService(
        store,
        {WorkflowName.EVALUATE_QUALITY: lambda request: {"received": request}},
    )
    service.initialize()
    server = create_http_server(service, host="127.0.0.1", port=0, bearer_token=_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, service
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    authenticated: bool = True,
    content_type: str | None = "application/json",
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], http.client.HTTPMessage]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    headers: dict[str, str] = {}
    if authenticated:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    if body is not None and content_type is not None:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read())
    status = response.status
    response_headers = response.headers
    connection.close()
    return status, payload, response_headers


def _raw_request(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    *,
    authenticated: bool = False,
) -> tuple[int, bytes, http.client.HTTPMessage]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    headers = {"Authorization": f"Bearer {_TOKEN}"} if authenticated else {}
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    status = response.status
    response_headers = response.headers
    connection.close()
    return status, body, response_headers


def test_http_health_authentication_and_security_headers(
    backend_server: tuple[ThreadingHTTPServer, BackendService],
) -> None:
    server, _ = backend_server
    status, payload, headers = _request(server, "GET", "/healthz", authenticated=False)
    assert status == HTTPStatus.OK
    assert payload == {"status": "ok"}
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Python" not in headers["Server"]

    status, payload, headers = _request(server, "GET", "/readyz", authenticated=False)
    assert status == HTTPStatus.OK
    assert payload == {"status": "ready"}

    status, payload, headers = _request(server, "GET", "/v1/metrics", authenticated=False)
    assert status == HTTPStatus.UNAUTHORIZED
    assert payload["error"] == {"code": "unauthorized", "message": "authentication required"}
    assert headers["WWW-Authenticate"] == 'Bearer realm="pagetrace"'


def test_http_submit_execute_inspect_events_and_metrics(
    backend_server: tuple[ThreadingHTTPServer, BackendService],
) -> None:
    server, service = backend_server
    body = json.dumps(
        {
            "workflow": "evaluate_quality",
            "request": {"value": 42},
            "idempotency_key": "http-request-1",
            "max_attempts": 1,
        }
    ).encode()
    status, payload, _ = _request(server, "POST", "/v1/jobs", body=body)
    assert status == HTTPStatus.ACCEPTED
    assert payload["created"] is True
    job = payload["job"]
    assert isinstance(job, dict)
    job_id = job["job_id"]
    assert isinstance(job_id, str)
    assert "request" not in job

    status, replay, _ = _request(server, "POST", "/v1/jobs", body=body)
    assert status == HTTPStatus.OK
    assert replay["created"] is False

    result = service.run_next()
    assert result is not None
    assert result.status is JobStatus.SUCCEEDED
    status, inspected, _ = _request(server, "GET", f"/v1/jobs/{job_id}", content_type=None)
    assert status == HTTPStatus.OK
    assert inspected["job"]["result"] == {"received": {"value": 42}}  # type: ignore[index]

    status, events, _ = _request(
        server, "GET", f"/v1/jobs/{job_id}/events?after_sequence=0&limit=10", content_type=None
    )
    assert status == HTTPStatus.OK
    event_items = cast(list[dict[str, object]], events["events"])
    assert [event["event_type"] for event in event_items] == [
        "submitted",
        "started",
        "succeeded",
    ]
    status, metrics, _ = _request(server, "GET", "/v1/metrics", content_type=None)
    assert status == HTTPStatus.OK
    assert metrics["metrics"]["succeeded"] == 1  # type: ignore[index]


def test_http_cancel_and_error_mapping(
    backend_server: tuple[ThreadingHTTPServer, BackendService],
) -> None:
    server, _ = backend_server
    submission = {
        "workflow": "evaluate_quality",
        "request": {},
        "idempotency_key": "cancel-me",
    }
    _, payload, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(submission).encode())
    job_id = payload["job"]["job_id"]  # type: ignore[index]
    status, cancelled, _ = _request(server, "POST", f"/v1/jobs/{job_id}/cancel", body=b"{}")
    assert status == HTTPStatus.OK
    assert cancelled["job"]["status"] == "cancelled"  # type: ignore[index]

    status, payload, _ = _request(server, "GET", "/v1/jobs/job-00000000000000000000000000000000")
    assert status == HTTPStatus.NOT_FOUND
    assert payload["error"]["code"] == "not_found"  # type: ignore[index]

    status, payload, _ = _request(server, "GET", f"/v1/jobs/{job_id}/events?broken")
    assert status == HTTPStatus.BAD_REQUEST
    status, payload, headers = _request(server, "DELETE", f"/v1/jobs/{job_id}")
    assert status == HTTPStatus.METHOD_NOT_ALLOWED
    assert headers["Allow"] == "GET, HEAD, POST"
    status, _, _ = _request(server, "GET", "/v1/unknown")
    assert status == HTTPStatus.NOT_FOUND


def test_http_rejects_invalid_fields_bodies_queries_and_credentials(
    backend_server: tuple[ThreadingHTTPServer, BackendService],
) -> None:
    server, _ = backend_server
    cases = (
        {"workflow": "unknown", "request": {}, "idempotency_key": "one"},
        {"workflow": "evaluate_quality", "request": [], "idempotency_key": "two"},
        {
            "workflow": "evaluate_quality",
            "request": {},
            "idempotency_key": "three",
            "max_attempts": True,
        },
        {"workflow": "evaluate_quality", "request": {}, "idempotency_key": "four", "x": 1},
    )
    for case in cases:
        status, payload, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(case).encode())
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"]["code"] == "invalid_request"  # type: ignore[index]

    status, _, _ = _request(
        server,
        "GET",
        "/v1/metrics",
        extra_headers={"Authorization": "Bearer wrong-token"},
    )
    assert status == HTTPStatus.UNAUTHORIZED
    status, _, _ = _request(server, "GET", "/v1/metrics", body=b"{}")
    assert status == HTTPStatus.BAD_REQUEST
    status, _, _ = _request(
        server, "GET", "/v1/metrics", extra_headers={"Transfer-Encoding": "chunked"}
    )
    assert status == HTTPStatus.BAD_REQUEST

    submission = {
        "workflow": "evaluate_quality",
        "request": {},
        "idempotency_key": "cancel-body",
    }
    _, payload, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(submission).encode())
    job_id = payload["job"]["job_id"]  # type: ignore[index]
    status, _, _ = _request(
        server, "POST", f"/v1/jobs/{job_id}/cancel", body=b'{"unexpected":true}'
    )
    assert status == HTTPStatus.BAD_REQUEST
    status, _, _ = _request(server, "GET", f"/v1/jobs/{job_id}/events?limit=not-an-integer")
    assert status == HTTPStatus.BAD_REQUEST


def test_http_conflict_capacity_readiness_and_internal_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteJobStore(
        tmp_path / "bounded-http.sqlite3", limits=BackendLimits(max_queued_jobs=1)
    )
    service = BackendService(store, {})
    service.initialize()
    server = create_http_server(service, host="127.0.0.1", port=0, bearer_token=_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = {
            "workflow": "evaluate_quality",
            "request": {"value": 1},
            "idempotency_key": "same-key",
        }
        status, _, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(first).encode())
        assert status == HTTPStatus.ACCEPTED
        changed = {**first, "request": {"value": 2}}
        status, _, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(changed).encode())
        assert status == HTTPStatus.CONFLICT
        second = {**first, "idempotency_key": "other-key"}
        status, _, _ = _request(server, "POST", "/v1/jobs", body=json.dumps(second).encode())
        assert status == HTTPStatus.TOO_MANY_REQUESTS

        def unavailable() -> object:
            raise BackendPersistenceError("database unavailable")

        monkeypatch.setattr(store, "health_check", unavailable)
        status, payload, _ = _request(server, "GET", "/readyz", authenticated=False)
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        assert payload == {"status": "unavailable"}
        monkeypatch.setattr(service, "metrics", unavailable)
        status, _, _ = _request(server, "GET", "/v1/metrics")
        assert status == HTTPStatus.SERVICE_UNAVAILABLE

        def internal() -> object:
            raise BackendError("internal")

        monkeypatch.setattr(service, "metrics", internal)
        status, payload, _ = _request(server, "GET", "/v1/metrics")
        assert status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert payload["error"] == {"code": "internal_error", "message": "request failed"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b'{"workflow":"evaluate_quality","workflow":"ingest_document"}', "application/json"),
        (b'{"value":NaN}', "application/json"),
        (b"[]", "application/json"),
        (b"{}", "text/plain"),
        (b"{}", "application/json; charset=utf-16"),
        (b"", "application/json"),
    ],
)
def test_http_rejects_malformed_submission(
    backend_server: tuple[ThreadingHTTPServer, BackendService], body: bytes, content_type: str
) -> None:
    server, _ = backend_server
    status, payload, _ = _request(server, "POST", "/v1/jobs", body=body, content_type=content_type)
    assert status == HTTPStatus.BAD_REQUEST
    assert payload["error"]["code"] == "invalid_request"  # type: ignore[index]


def test_http_server_configuration_validation(tmp_path: Path) -> None:
    service = BackendService(SqliteJobStore(tmp_path / "db.sqlite3"), {})
    service.initialize()
    with pytest.raises(ValueError, match="loopback"):
        create_http_server(service, host="0.0.0.0", port=1, bearer_token=_TOKEN)
    with pytest.raises(ValueError, match="port"):
        create_http_server(service, host="127.0.0.1", port=-1, bearer_token=_TOKEN)
    with pytest.raises(ValueError, match="bearer token"):
        create_http_server(service, host="127.0.0.1", port=1, bearer_token="short")
    with pytest.raises(ValueError, match="positive integer"):
        create_http_server(
            service,
            host="127.0.0.1",
            port=1,
            bearer_token=_TOKEN,
            max_request_bytes=0,
        )
    missing = tmp_path / "missing-web"
    with pytest.raises(ValueError, match="web root"):
        create_http_server(
            service,
            host="127.0.0.1",
            port=1,
            bearer_token=_TOKEN,
            web_root=missing,
        )


def test_http_serves_packaged_web_assets_with_browser_security_headers(tmp_path: Path) -> None:
    store = SqliteJobStore(tmp_path / "web.sqlite3")
    service = BackendService(store, {})
    service.initialize()
    web_root = tmp_path / "web"
    assets = web_root / "assets"
    assets.mkdir(parents=True)
    (web_root / "index.html").write_text(
        "<!doctype html><title>PageTrace</title>", encoding="utf-8"
    )
    (assets / "app-abc123.js").write_text("console.log('PageTrace')", encoding="utf-8")
    server = create_http_server(
        service,
        host="127.0.0.1",
        port=0,
        bearer_token=_TOKEN,
        web_root=web_root,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, headers = _raw_request(server, "GET", "/")
        assert status == HTTPStatus.OK
        assert b"PageTrace" in body
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert headers["Cache-Control"] == "no-store"
        assert headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in headers["Permissions-Policy"]

        status, body, headers = _raw_request(server, "HEAD", "/index.html")
        assert status == HTTPStatus.OK
        assert body == b""
        assert int(headers["Content-Length"]) > 0

        status, body, headers = _raw_request(server, "GET", "/assets/app-abc123.js")
        assert status == HTTPStatus.OK
        assert body == b"console.log('PageTrace')"
        assert headers["Content-Type"] == "text/javascript; charset=utf-8"
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"

        status, payload, _ = _request(
            server, "GET", "/assets/missing.js", authenticated=False, content_type=None
        )
        assert status == HTTPStatus.NOT_FOUND
        assert payload["error"] == {"code": "not_found", "message": "resource was not found"}
        status, _, _ = _request(
            server, "GET", "/assets/../index.html", authenticated=False, content_type=None
        )
        assert status == HTTPStatus.UNAUTHORIZED
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_rejects_symlinked_static_asset(tmp_path: Path) -> None:
    store = SqliteJobStore(tmp_path / "web-symlink.sqlite3")
    service = BackendService(store, {})
    service.initialize()
    web_root = tmp_path / "web"
    assets = web_root / "assets"
    assets.mkdir(parents=True)
    (web_root / "index.html").write_text("PageTrace", encoding="utf-8")
    target = tmp_path / "outside.js"
    target.write_text("secret", encoding="utf-8")
    link = assets / "linked.js"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available")
    server = create_http_server(
        service,
        host="127.0.0.1",
        port=0,
        bearer_token=_TOKEN,
        web_root=web_root,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload, _ = _request(
            server, "GET", "/assets/linked.js", authenticated=False, content_type=None
        )
        assert status == HTTPStatus.NOT_FOUND
        assert payload["error"]["code"] == "not_found"  # type: ignore[index]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
