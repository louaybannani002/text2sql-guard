"""Structured (JSON) logging setup. The only sanctioned way to log.

Every line of an HTTP request carries ``request_id`` and ``user_id`` (bound as context
variables by the API). A last-resort processor redacts values under keys that may hold
secrets, question text, SQL or result rows, in case a caller passes one by mistake.
"""

import logging
import re
import sys
from collections.abc import MutableMapping

import structlog

REDACTED = "[redacted]"
_SENSITIVE_KEYS = frozenset(
    {
        "question",
        "sql",
        "rows",
        "row",
        "prompt",
        "messages",
        "raw_output",
        "authorization",
        "token",
        "access_token",
        "password",
        "secret",
        "api_key",
    }
)
_SENSITIVE_SUFFIX = re.compile(r"(_password|_secret|_api_key|_secret_key|_token|_url)$")


def redact_sensitive(
    logger: object, method: str, event: MutableMapping[str, object]
) -> MutableMapping[str, object]:
    """Replace the values of sensitive keys (structlog processor)."""
    del logger, method
    for key in list(event):
        if key in _SENSITIVE_KEYS or _SENSITIVE_SUFFIX.search(key):
            event[key] = REDACTED
    return event


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    """Configure structlog and route stdlib logging through it.

    Args:
        level: Minimum log level name, e.g. ``"INFO"``.
        json: Render JSON lines (production) instead of colored console output.
    """
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        # No explicit file: stdout is looked up at write time, so a replaced sys.stdout
        # (test capture, reconfigured streams) is honoured instead of a stale handle.
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout, force=True)


def bind_user(user_id: str) -> None:
    """Add ``user_id`` to every following log line of the current request."""
    structlog.contextvars.bind_contextvars(user_id=user_id)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name``."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
