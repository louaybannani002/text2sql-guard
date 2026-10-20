"""One entry point for observing answered requests: Langfuse traces and Prometheus metrics.

Built from ``Settings``. Tracing is a no-op unless ``LANGFUSE_ENABLED`` is true and the host
and both keys are set; metrics are off when ``METRICS_ENABLED`` is false. ``record`` never
raises: observability must not break or slow a request.
"""

from prometheus_client import CollectorRegistry

from text2sql.config.settings import Settings
from text2sql.observability.langfuse_client import LangfuseSink, NoopSink, TraceSink
from text2sql.observability.langfuse_spans import RequestInfo, TraceConfig, trace_spans
from text2sql.observability.logging import get_logger
from text2sql.observability.metrics import PipelineMetrics
from text2sql.pipeline.answer import Answer

log = get_logger(__name__)


class Observer:
    """Records each request's answer as a trace and as metrics."""

    def __init__(
        self, config: TraceConfig, *, sink: TraceSink, metrics: PipelineMetrics | None
    ) -> None:
        """Explicit parts (tests pass fakes)."""
        self.config, self.sink, self.metrics = config, sink, metrics

    @classmethod
    def disabled(cls) -> "Observer":
        """No tracing, no metrics."""
        return cls(TraceConfig("disabled", "-", "-"), sink=NoopSink(), metrics=None)

    @property
    def tracing(self) -> bool:
        """Whether traces are sent anywhere."""
        return not isinstance(self.sink, NoopSink)

    def record(self, answer: Answer | None, request: RequestInfo) -> None:
        """Trace and count one request (``answer`` None: it crashed). Never raises."""
        try:
            if answer is None:
                if self.metrics is not None:
                    self.metrics.crashed()
                return
            if self.metrics is not None:
                self.metrics.observe(answer, guard_layer=request.guard_layer)
            self.sink.submit(trace_spans(answer, request, self.config))
        except Exception as exc:  # noqa: BLE001 - observability never breaks a request
            log.warning("observe_failed", error=type(exc).__name__)

    async def aclose(self) -> None:
        """Flush pending traces."""
        await self.sink.aclose()


def langfuse_sink(settings: Settings) -> TraceSink:
    """A real sink when Langfuse is enabled and fully configured, otherwise a no-op."""
    public, secret, host = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
    )
    if not settings.langfuse_enabled or public is None or secret is None or host is None:
        return NoopSink()
    if not public.get_secret_value() or not secret.get_secret_value():
        return NoopSink()
    return LangfuseSink(
        str(host),
        public.get_secret_value(),
        secret.get_secret_value(),
        environment=settings.app_env,
    )


def build_observer(
    settings: Settings,
    *,
    generate_prompt: str,
    guard_prompt: str,
    sink: TraceSink | None = None,
) -> Observer:
    """The observer for this process (``sink`` overrides the Langfuse sink, for tests)."""
    free_tier = frozenset(p.lower() for p in settings.llm_free_tier_providers)
    config = TraceConfig(
        environment=settings.app_env,
        generate_prompt=generate_prompt,
        guard_prompt=guard_prompt,
        free_tier_providers=free_tier,
        capture_question=settings.langfuse_capture_question,
    )
    metrics = (
        PipelineMetrics(CollectorRegistry(), free_tier_providers=free_tier)
        if settings.metrics_enabled
        else None
    )
    observer = Observer(config, sink=sink or langfuse_sink(settings), metrics=metrics)
    log.info("observability", tracing=observer.tracing, metrics=metrics is not None)
    return observer
