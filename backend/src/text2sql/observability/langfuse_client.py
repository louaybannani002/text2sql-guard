"""Send spans to Langfuse's OpenTelemetry endpoint (OTLP/HTTP, JSON) in the background.

``submit`` never blocks or raises: each batch is posted by its own task (at most a few at a
time) and failures are logged with counts and status codes only, never span content. A request
is never slowed down or failed by tracing. ``aclose`` waits briefly for pending sends.
OTLP is Langfuse's supported ingestion path (the legacy ``/api/public/ingestion`` is sunset).
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol

import httpx

from text2sql.observability.langfuse_spans import Span, attributes
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

OTLP_PATH = "/api/public/otel/v1/traces"
SERVICE_NAME = "text2sql-guard"
_MAX_IN_FLIGHT = 4
_MAX_PENDING = 100


class TraceSink(Protocol):
    """Where trace spans go."""

    def submit(self, spans: Sequence[Span]) -> None:
        """Queue spans for sending; never raises."""
        ...

    async def aclose(self) -> None:
        """Flush what is pending and release resources."""
        ...


class NoopSink:
    """Tracing disabled (or not configured): drop everything."""

    def submit(self, spans: Sequence[Span]) -> None:
        """Drop ``spans``."""
        del spans

    async def aclose(self) -> None:
        """Nothing to release."""


def otlp_payload(spans: Sequence[Span], *, environment: str | None = None) -> dict[str, object]:
    """An OTLP ``ExportTraceServiceRequest`` in its JSON form."""
    resource = attributes({"service.name": SERVICE_NAME, "deployment.environment": environment})
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": resource},
                "scopeSpans": [{"scope": {"name": SERVICE_NAME}, "spans": list(spans)}],
            }
        ]
    }


class LangfuseSink:
    """Posts each submitted batch to ``<host>/api/public/otel/v1/traces``."""

    def __init__(  # noqa: PLR0913 - explicit connection settings
        self,
        host: str,
        public_key: str,
        secret_key: str,
        *,
        environment: str | None = None,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """``transport`` lets tests replace the network."""
        self._client = httpx.AsyncClient(
            base_url=host.rstrip("/"),
            auth=(public_key, secret_key),
            timeout=timeout_s,
            transport=transport,
        )
        self._environment = environment
        self._slots = asyncio.Semaphore(_MAX_IN_FLIGHT)
        self._pending: set[asyncio.Task[None]] = set()

    def submit(self, spans: Sequence[Span]) -> None:
        """Send ``spans`` in a background task (dropped if too many sends are pending)."""
        if not spans:
            return
        if len(self._pending) >= _MAX_PENDING:
            log.warning("langfuse_backlog_full", dropped_spans=len(spans))
            return
        task = asyncio.get_running_loop().create_task(self._send(list(spans)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _send(self, spans: list[Span]) -> None:
        payload = otlp_payload(spans, environment=self._environment)
        async with self._slots:
            try:
                response = await self._client.post(OTLP_PATH, json=payload)
            except httpx.HTTPError as exc:
                log.warning("langfuse_send_failed", error=type(exc).__name__, spans=len(spans))
                return
        if response.status_code >= httpx.codes.BAD_REQUEST:
            log.warning("langfuse_rejected", status=response.status_code, spans=len(spans))
            return
        if rejected := _rejected_spans(response):
            log.warning("langfuse_partial", rejected=rejected, spans=len(spans))

    async def aclose(self, timeout_s: float = 5.0) -> None:
        """Wait up to ``timeout_s`` for pending sends, then close the client."""
        if self._pending:
            _, late = await asyncio.wait(set(self._pending), timeout=timeout_s)
            for task in late:
                task.cancel()
            if late:
                log.warning("langfuse_flush_timeout", unsent_batches=len(late))
        await self._client.aclose()


def _rejected_spans(response: httpx.Response) -> int:
    """``partialSuccess.rejectedSpans`` of an OTLP response (0 when all were accepted)."""
    try:
        body = response.json()
    except ValueError:
        return 0
    partial = body.get("partialSuccess") if isinstance(body, dict) else None
    rejected = partial.get("rejectedSpans") if isinstance(partial, dict) else None
    try:
        return int(rejected or 0)
    except (TypeError, ValueError):
        return 0
