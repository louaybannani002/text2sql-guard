"""Pure ASGI middleware (``BaseHTTPMiddleware`` would buffer the SSE stream).

- ``RequestIdMiddleware``: accept a sane ``X-Request-ID`` or create one, expose it on the
  response, bind it to every log line of the request, and log one access line.
- ``BodySizeLimitMiddleware``: reject bodies over the limit, by ``Content-Length`` and by the
  bytes actually received (a client can lie about the header or omit it).
"""

import contextlib
import json
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from text2sql.observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import MutableMapping

log = get_logger(__name__)

REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


def _error_body(code: str, message: str, request_id: str | None) -> bytes:
    error = {"code": code, "message": message, "request_id": request_id}
    return json.dumps({"error": error}).encode()


def _start(status: int, length: int) -> Message:
    headers = [(b"content-type", b"application/json"), (b"content-length", str(length).encode())]
    return {"type": "http.response.start", "status": status, "headers": headers}


class RequestIdMiddleware:
    """Request IDs and access logging."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, REQUEST_ID_HEADER)
        request_id = (
            incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        )
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        started = time.perf_counter()
        status: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
                message["headers"] = headers
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception as exc:  # noqa: BLE001 - last line: never let a traceback out
                # Swallowed rather than re-raised: the server would log the message, which can
                # hold SQL or data. Only the type is logged.
                log.error("unhandled_error", error=type(exc).__name__)  # noqa: TRY400 - no message
                if status is None:
                    body = _error_body(
                        "internal_error", "Something went wrong. Please try again.", request_id
                    )
                    await send_with_id(_start(500, len(body)))
                    await send_with_id({"type": "http.response.body", "body": body})
                status = 500
            finally:
                log.info(
                    "http_request",
                    method=scope["method"],
                    path=scope["path"],  # never the query string: it may carry data
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        """Wrap ``app``."""
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = _error_body(
            "payload_too_large", f"The request body exceeds {self.max_bytes} bytes.", request_id
        )
        await send(_start(413, len(body)))
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await self._reject(scope, send)
            return

        received = 0
        responded = False

        async def guarded_send(message: Message) -> None:
            if not responded:  # after our 413, whatever the app tries to send is dropped
                await send(message)

        async def counting_receive() -> Message:
            nonlocal received, responded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Respond now: FastAPI turns any body-read exception into its own 400.
                    if not responded:
                        await self._reject(scope, send)
                        responded = True
                    msg = "request body too large"
                    raise _BodyTooLargeError(msg)
            return message

        with contextlib.suppress(_BodyTooLargeError):  # the 413 has already been sent
            await self.app(scope, counting_receive, guarded_send)


class _BodyTooLargeError(Exception):
    """Raised mid-read when a body without (or with a false) Content-Length is too big."""
