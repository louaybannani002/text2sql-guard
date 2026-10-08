"""One error shape for every failure: ``{"error": {"code", "message", "request_id"}}``.

Messages are written for clients. Stack traces, SQL and database/driver messages never reach a
response: unexpected exceptions become a generic 500 and are logged with the request ID.
"""

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from text2sql.observability.logging import get_logger

log = get_logger(__name__)


class ErrorBody(BaseModel):
    """The ``error`` object."""

    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx JSON response."""

    error: ErrorBody


class ApiError(Exception):
    """Raise from routes and dependencies; rendered as ``ErrorResponse``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Status, a stable machine-readable code, and a client-safe message."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


_SERVER_ERROR = 500
_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def request_id_of(request: Request) -> str | None:
    """The request ID set by ``RequestIdMiddleware``."""
    value = request.scope.get("state", {}).get("request_id")
    return value if isinstance(value, str) else None


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the uniform error response."""
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id_of(request))
    )
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # registered for ApiError only; be safe anyway
        return await _unexpected_error(request, exc)
    return error_response(request, exc.status_code, exc.code, exc.message, exc.headers)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return await _unexpected_error(request, exc)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if exc.status_code < _SERVER_ERROR else code
    return error_response(request, exc.status_code, code, message, dict(exc.headers or {}))


def _field(error: Mapping[str, object]) -> str:
    """``question`` / ``items.0.name``; ``body`` for malformed JSON (its loc is an offset)."""
    loc = error.get("loc", ())
    if error.get("type") == "json_invalid" or not isinstance(loc, tuple):
        return "body"
    return ".".join(str(part) for part in loc[1:]) or "body"


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await _unexpected_error(request, exc)
    # Only where and what kind: pydantic's messages can echo the (untrusted) input back.
    fields = sorted({_field(e) for e in exc.errors()})
    message = f"Invalid request: check {', '.join(fields)}."
    return error_response(request, 422, "invalid_request", message)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", error=type(exc).__name__, request_id=request_id_of(request))
    return error_response(request, 500, "internal_error", "Something went wrong. Please try again.")


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers that produce ``ErrorResponse``."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
