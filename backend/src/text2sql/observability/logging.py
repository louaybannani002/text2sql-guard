"""Structured (JSON) logging setup. The only sanctioned way to log."""

import logging
import sys

import structlog


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


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name``."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
