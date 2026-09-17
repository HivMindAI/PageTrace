"""Small authenticated JSON HTTP boundary for the PageTrace backend service."""

from __future__ import annotations

import hmac
import json
import logging
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from pagetrace.backend.errors import (
    BackendCapacityError,
    BackendConflictError,
    BackendError,
    BackendInputError,
    BackendNotFoundError,
    BackendPersistenceError,
)
from pagetrace.backend.models import (
    WorkflowName,
    canonical_json,
    event_public_payload,
    job_public_payload,
    metrics_payload,
)
from pagetrace.backend.service import BackendService

_JOB_PATH = re.compile(r"^/v1/jobs/(job-[0-9a-f]{32})$")
_EVENT_PATH = re.compile(r"^/v1/jobs/(job-[0-9a-f]{32})/events$")
_CANCEL_PATH = re.compile(r"^/v1/jobs/(job-[0-9a-f]{32})/cancel$")
_LOG = logging.getLogger(__name__)


def create_http_server(
    service: BackendService,
    *,
    host: str,
    port: int,
    bearer_token: str,
    max_request_bytes: int | None = None,
) -> ThreadingHTTPServer:
    """Create a loopback-only authenticated server without starting it."""

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("backend HTTP server only supports loopback binding")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("port must be an integer from 0 to 65535")
    if (
        not isinstance(bearer_token, str)
        or not 32 <= len(bearer_token) <= 512
        or any(character.isspace() or ord(character) < 33 for character in bearer_token)
    ):
        raise ValueError("bearer token must contain 32 to 512 non-whitespace characters")
    body_limit = (
        service.store.limits.max_request_bytes if max_request_bytes is None else max_request_bytes
    )
    if isinstance(body_limit, bool) or not isinstance(body_limit, int) or body_limit < 1:
        raise ValueError("max_request_bytes must be a positive integer")
    handler = _handler_type(service, bearer_token.encode(), body_limit)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def _handler_type(
    service: BackendService, bearer_token: bytes, max_request_bytes: int
) -> type[BaseHTTPRequestHandler]:
    class BackendRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PageTrace"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._method_not_allowed()

        def do_PATCH(self) -> None:
            self._method_not_allowed()

        def do_DELETE(self) -> None:
            self._method_not_allowed()

        def do_OPTIONS(self) -> None:
            self._method_not_allowed()

        def log_message(self, format: str, *args: object) -> None:
            _LOG.info("backend HTTP request", extra={"client": self.client_address[0]})

        def version_string(self) -> str:
            return "PageTrace"

        def _dispatch(self, method: str) -> None:
            try:
                if self.headers.get("Transfer-Encoding") is not None:
                    raise BackendInputError("transfer encoding is not supported")
                parsed = urlsplit(self.path)
                if parsed.fragment:
                    raise BackendInputError("request target is invalid")
                if method == "GET" and parsed.path == "/healthz" and not parsed.query:
                    self._send(HTTPStatus.OK, {"status": "ok"})
                    return
                if method == "GET" and parsed.path == "/readyz" and not parsed.query:
                    ready = service.ready()
                    self._send(
                        HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                        {"status": "ready" if ready else "unavailable"},
                    )
                    return
                if not self._authenticated():
                    self._send(
                        HTTPStatus.UNAUTHORIZED,
                        {"error": {"code": "unauthorized", "message": "authentication required"}},
                        authenticate=True,
                    )
                    return
                self._dispatch_authenticated(method, parsed.path, parsed.query)
            except BackendError as exc:
                self._send_backend_error(exc)
            except (ConnectionError, OSError):
                return
            except Exception:
                _LOG.exception("unexpected backend HTTP failure")
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": {"code": "internal_error", "message": "request failed"}},
                )

        def _dispatch_authenticated(self, method: str, path: str, query: str) -> None:
            if method == "POST" and path == "/v1/jobs" and not query:
                body = self._read_json_object()
                allowed = {"workflow", "request", "idempotency_key", "max_attempts"}
                if set(body) - allowed or not {"workflow", "request", "idempotency_key"}.issubset(
                    body
                ):
                    raise BackendInputError("job submission has missing or unknown fields")
                workflow_value = body["workflow"]
                if not isinstance(workflow_value, str):
                    raise BackendInputError("workflow is not supported")
                try:
                    workflow = WorkflowName(workflow_value)
                except (TypeError, ValueError) as exc:
                    raise BackendInputError("workflow is not supported") from exc
                request = body["request"]
                key = body["idempotency_key"]
                max_attempts = body.get("max_attempts")
                if not isinstance(request, dict) or not isinstance(key, str):
                    raise BackendInputError("request and idempotency_key have invalid types")
                if max_attempts is not None and (
                    isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
                ):
                    raise BackendInputError("max_attempts must be an integer")
                job, created = service.submit(
                    workflow,
                    cast(dict[str, object], request),
                    idempotency_key=key,
                    max_attempts=max_attempts,
                )
                self._send(
                    HTTPStatus.ACCEPTED if created else HTTPStatus.OK,
                    {"created": created, "job": job_public_payload(job)},
                )
                return
            match = _JOB_PATH.fullmatch(path)
            if method == "GET" and match is not None and not query:
                self._reject_request_body()
                self._send(HTTPStatus.OK, {"job": job_public_payload(service.get(match.group(1)))})
                return
            match = _EVENT_PATH.fullmatch(path)
            if method == "GET" and match is not None:
                self._reject_request_body()
                try:
                    parameters = parse_qs(query, keep_blank_values=True, strict_parsing=True)
                except ValueError as exc:
                    raise BackendInputError("event query parameters are invalid") from exc
                if set(parameters) - {"after_sequence", "limit"} or any(
                    len(values) != 1 for values in parameters.values()
                ):
                    raise BackendInputError("event query parameters are invalid")
                after = _query_integer(parameters, "after_sequence", 0)
                limit = _query_integer(parameters, "limit", 100)
                events = service.events(match.group(1), after_sequence=after, limit=limit)
                self._send(
                    HTTPStatus.OK,
                    {"events": [event_public_payload(event) for event in events]},
                )
                return
            match = _CANCEL_PATH.fullmatch(path)
            if method == "POST" and match is not None and not query:
                self._read_empty_or_object()
                job = service.cancel(match.group(1))
                self._send(HTTPStatus.OK, {"job": job_public_payload(job)})
                return
            if method == "GET" and path == "/v1/metrics" and not query:
                self._reject_request_body()
                self._send(HTTPStatus.OK, {"metrics": metrics_payload(service.metrics())})
                return
            self._send(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "not_found", "message": "resource was not found"}},
            )

        def _authenticated(self) -> bool:
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1:
                return False
            supplied = values[0].encode("utf-8", "surrogateescape")
            expected = b"Bearer " + bearer_token
            return hmac.compare_digest(supplied, expected)

        def _read_json_object(self) -> dict[str, object]:
            content_types = self.headers.get_all("Content-Type", [])
            if len(content_types) != 1:
                raise BackendInputError("Content-Type must be application/json")
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                raise BackendInputError("Content-Type must be application/json")
            charset = self.headers.get_param("charset")
            if charset is not None and (
                not isinstance(charset, str) or charset.lower() not in {"utf-8", "utf8"}
            ):
                raise BackendInputError("JSON request charset must be UTF-8")
            content_lengths = self.headers.get_all("Content-Length", [])
            if len(content_lengths) != 1:
                raise BackendInputError("Content-Length is required")
            content_length = content_lengths[0]
            try:
                length = int(content_length)
            except ValueError as exc:
                raise BackendInputError("Content-Length is invalid") from exc
            if length < 1 or length > max_request_bytes:
                raise BackendInputError("request body size is outside the configured limit")
            data = self.rfile.read(length)
            if len(data) != length:
                raise BackendInputError("request body was incomplete")
            try:
                value = json.loads(
                    data.decode("utf-8"),
                    parse_constant=_reject_constant,
                    object_pairs_hook=_unique_object,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise BackendInputError("request body must be strict UTF-8 JSON") from exc
            if not isinstance(value, dict):
                raise BackendInputError("request body must be a JSON object")
            return cast(dict[str, object], value)

        def _read_empty_or_object(self) -> None:
            content_lengths = self.headers.get_all("Content-Length", [])
            if not content_lengths:
                return
            if len(content_lengths) != 1:
                raise BackendInputError("Content-Length is invalid")
            if content_lengths[0] == "0":
                return
            body = self._read_json_object()
            if body:
                raise BackendInputError("cancellation body must be an empty JSON object")

        def _reject_request_body(self) -> None:
            content_lengths = self.headers.get_all("Content-Length", [])
            if len(content_lengths) > 1 or (content_lengths and content_lengths[0] != "0"):
                raise BackendInputError("GET requests must not contain a body")

        def _method_not_allowed(self) -> None:
            self._send(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": {"code": "method_not_allowed", "message": "method is not allowed"}},
                allow="GET, POST",
            )

        def _send_backend_error(self, error: BackendError) -> None:
            if isinstance(error, BackendInputError):
                status, code = HTTPStatus.BAD_REQUEST, "invalid_request"
            elif isinstance(error, BackendNotFoundError):
                status, code = HTTPStatus.NOT_FOUND, "not_found"
            elif isinstance(error, BackendConflictError):
                status, code = HTTPStatus.CONFLICT, "conflict"
            elif isinstance(error, BackendCapacityError):
                status, code = HTTPStatus.TOO_MANY_REQUESTS, "capacity_exceeded"
            elif isinstance(error, BackendPersistenceError):
                status, code = HTTPStatus.SERVICE_UNAVAILABLE, "service_unavailable"
            else:
                status, code = HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error"
            message = (
                str(error) if status is not HTTPStatus.INTERNAL_SERVER_ERROR else "request failed"
            )
            self._send(status, {"error": {"code": code, "message": message}})

        def _send(
            self,
            status: HTTPStatus,
            payload: object,
            *,
            authenticate: bool = False,
            allow: str | None = None,
        ) -> None:
            body = canonical_json(payload) + b"\n"
            self.close_connection = True
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            if authenticate:
                self.send_header("WWW-Authenticate", 'Bearer realm="pagetrace"')
            if allow is not None:
                self.send_header("Allow", allow)
            self.end_headers()
            self.wfile.write(body)

    return BackendRequestHandler


def _reject_constant(value: str) -> Any:
    raise ValueError(f"invalid numeric constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _query_integer(parameters: dict[str, list[str]], name: str, default: int) -> int:
    values = parameters.get(name)
    if values is None:
        return default
    try:
        return int(values[0])
    except ValueError as exc:
        raise BackendInputError(f"{name} must be an integer") from exc
