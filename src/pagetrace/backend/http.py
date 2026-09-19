"""Small authenticated JSON HTTP boundary for the PageTrace backend service."""

from __future__ import annotations

import hmac
import json
import logging
import math
import re
import socket
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
_STATIC_PATH = re.compile(r"^/assets/[A-Za-z0-9._-]+$")
_STATIC_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}
_MAX_STATIC_BYTES = 10 * 1024 * 1024
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
_LOG = logging.getLogger(__name__)


class _LoopbackHTTPServer(ThreadingHTTPServer):
    """Threaded local server with enough backlog for rapid browser API polling."""

    daemon_threads = True
    request_queue_size = 128

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        *,
        connection_timeout_seconds: float,
    ) -> None:
        self.connection_timeout_seconds = connection_timeout_seconds
        super().__init__(server_address, request_handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, client_address = super().get_request()
        request.settimeout(self.connection_timeout_seconds)
        return request, client_address


def create_http_server(
    service: BackendService,
    *,
    host: str,
    port: int,
    bearer_token: str,
    max_request_bytes: int | None = None,
    web_root: Path | None = None,
    connection_timeout_seconds: float = 10.0,
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
    if (
        isinstance(connection_timeout_seconds, bool)
        or not isinstance(connection_timeout_seconds, (int, float))
        or not math.isfinite(connection_timeout_seconds)
        or not 0.1 <= connection_timeout_seconds <= 300
    ):
        raise ValueError("connection_timeout_seconds must be from 0.1 through 300")
    static_root = _validate_web_root(web_root)
    handler = _handler_type(service, bearer_token.encode(), body_limit, static_root)
    server = _LoopbackHTTPServer(
        (host, port), handler, connection_timeout_seconds=float(connection_timeout_seconds)
    )
    return server


def _handler_type(
    service: BackendService,
    bearer_token: bytes,
    max_request_bytes: int,
    web_root: Path | None,
) -> type[BaseHTTPRequestHandler]:
    class BackendRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PageTrace"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_HEAD(self) -> None:
            self._dispatch("HEAD")

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
                self._validate_request_metadata()
                if self.headers.get("Transfer-Encoding") is not None:
                    raise BackendInputError("transfer encoding is not supported")
                parsed = urlsplit(self.path)
                if parsed.fragment:
                    raise BackendInputError("request target is invalid")
                if (
                    method in {"GET", "HEAD"}
                    and not parsed.query
                    and self._serve_static(parsed.path, head_only=method == "HEAD")
                ):
                    return
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

        def _validate_request_metadata(self) -> None:
            host_values = self.headers.get_all("Host", [])
            server_port = cast(ThreadingHTTPServer, self.server).server_port
            if len(host_values) != 1 or not _loopback_authority(host_values[0], server_port):
                raise BackendInputError("Host header is invalid")
            origin_values = self.headers.get_all("Origin", [])
            if len(origin_values) > 1 or (
                origin_values and not _loopback_origin(origin_values[0], server_port)
            ):
                raise BackendInputError("request origin is not allowed")

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

        def _serve_static(self, path: str, *, head_only: bool) -> bool:
            if web_root is None:
                return False
            if path in {"/", "/index.html"}:
                relative = Path("index.html")
            elif _STATIC_PATH.fullmatch(path) is not None:
                relative = Path(*path.lstrip("/").split("/"))
            else:
                return False
            try:
                candidate = _safe_static_file(web_root, relative)
                metadata = candidate.stat()
                if metadata.st_size > _MAX_STATIC_BYTES:
                    raise OSError("static asset is too large")
                body = candidate.read_bytes()
                if len(body) != metadata.st_size:
                    raise OSError("static asset changed while reading")
            except (OSError, ValueError):
                self._send(
                    HTTPStatus.NOT_FOUND,
                    {"error": {"code": "not_found", "message": "resource was not found"}},
                )
                return True
            media_type = _STATIC_MEDIA_TYPES.get(candidate.suffix.lower())
            if media_type is None:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    {"error": {"code": "not_found", "message": "resource was not found"}},
                )
                return True
            self.close_connection = True
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Cache-Control",
                "no-store"
                if candidate.name == "index.html"
                else "public, max-age=31536000, immutable",
            )
            self.send_header("Connection", "close")
            self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Permissions-Policy",
                "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
            )
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return True

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
                allow="GET, HEAD, POST",
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
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
            if authenticate:
                self.send_header("WWW-Authenticate", 'Bearer realm="pagetrace"')
            if allow is not None:
                self.send_header("Allow", allow)
            self.end_headers()
            self.wfile.write(body)

    return BackendRequestHandler


def _validate_web_root(web_root: Path | None) -> Path | None:
    if web_root is None:
        return None
    if not isinstance(web_root, Path):
        raise ValueError("web root must be a pathlib.Path")
    try:
        metadata = web_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("web root must be a non-symlink directory")
        resolved = web_root.resolve(strict=True)
        _safe_static_file(resolved, Path("index.html"))
        return resolved
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("web root must contain a readable regular index.html") from exc


def _loopback_authority(value: str, expected_port: int) -> bool:
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.hostname is not None
        and parsed.hostname.lower() in {"127.0.0.1", "::1", "localhost"}
        and (port if port is not None else 80) == expected_port
    )


def _loopback_origin(value: str, expected_port: int) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "http"
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
        and _loopback_authority(parsed.netloc, expected_port)
    )


def _safe_static_file(root: Path, relative: Path) -> Path:
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("static asset path is unsafe")
    current = root
    for part in relative.parts:
        current = current / part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("static asset path contains a symbolic link")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ValueError("static asset must be a regular file")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("static asset is outside the web root")
    return resolved


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
