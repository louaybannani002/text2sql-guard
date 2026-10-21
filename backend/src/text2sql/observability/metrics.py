"""Prometheus metrics of the question pipeline, derived from each answer's trace.

Labels are bounded (statuses, stage names, guard layers, providers, configured models), never
question text, SQL or user ids. The registry is passed in, so tests get a fresh one.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from text2sql.observability.langfuse_spans import call_cost
from text2sql.pipeline.answer import Answer

_SECONDS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0)


class PipelineMetrics:
    """Counters and histograms for ``/metrics``."""

    def __init__(
        self, registry: CollectorRegistry, *, free_tier_providers: frozenset[str] = frozenset()
    ) -> None:
        """Register every metric on ``registry``."""
        self.registry = registry
        self._free_tier = free_tier_providers
        self.queries = Counter(
            "t2s_queries", "Questions answered, by final status.", ["status"], registry=registry
        )
        self.query_seconds = Histogram(
            "t2s_query_duration_seconds",
            "End-to-end pipeline time per question.",
            buckets=_SECONDS,
            registry=registry,
        )
        self.stages = Counter(
            "t2s_stages",
            "Stage runs, by stage and outcome.",
            ["stage", "status"],
            registry=registry,
        )
        self.stage_seconds = Histogram(
            "t2s_stage_duration_seconds",
            "Time per stage run.",
            ["stage"],
            buckets=_SECONDS,
            registry=registry,
        )
        self.guard_blocks = Counter(
            "t2s_guard_blocks", "Questions stopped, by guard layer.", ["layer"], registry=registry
        )
        self.retries = Counter(
            "t2s_generation_retries", "SQL generation retries (repair loop).", registry=registry
        )
        self.fallbacks = Counter(
            "t2s_llm_fallbacks",
            "LLM calls answered by the fallback model after a rate limit.",
            ["role", "provider", "model"],
            registry=registry,
        )
        self.llm_calls = Counter(
            "t2s_llm_calls", "LLM and embedding calls.", ["provider", "model"], registry=registry
        )
        self.llm_tokens = Counter(
            "t2s_llm_tokens", "Tokens used.", ["provider", "model"], registry=registry
        )
        self.llm_cached_tokens = Counter(
            "t2s_llm_cached_tokens",
            "Prompt tokens served from the provider's prompt cache.",
            ["provider", "model"],
            registry=registry,
        )
        self.llm_cost = Counter(
            "t2s_llm_cost_usd",
            "Known LLM cost in USD (0 for free-tier providers).",
            ["provider"],
            registry=registry,
        )
        self.cache_hits = Counter(
            "t2s_cache_hits", "Answers served from the cache.", ["level"], registry=registry
        )
        self.crashes = Counter(
            "t2s_query_crashes", "Questions that crashed before an answer.", registry=registry
        )

    def observe(self, answer: Answer, *, guard_layer: str | None) -> None:
        """Count one answered question."""
        self.queries.labels(answer.status).inc()
        self.query_seconds.observe(answer.trace.total_ms / 1000)
        for stage in answer.trace.stages:
            self.stages.labels(stage.stage, stage.status).inc()
            self.stage_seconds.labels(stage.stage).observe(stage.latency_ms / 1000)
            for call in stage.calls:
                provider = call.provider or "unknown"
                self.llm_calls.labels(provider, call.model).inc()
                self.llm_tokens.labels(provider, call.model).inc(call.total_tokens)
                self.llm_cached_tokens.labels(provider, call.model).inc(call.cached_tokens)
                if (cost := call_cost(call, self._free_tier)) is not None:
                    self.llm_cost.labels(provider).inc(cost)
                if call.fallback:
                    self.fallbacks.labels(call.role, provider, call.model).inc()
        if guard_layer is not None:
            self.guard_blocks.labels(guard_layer).inc()
        if answer.attempts > 1:
            self.retries.inc(answer.attempts - 1)
        if answer.cache is not None:
            self.cache_hits.labels(answer.cache).inc()

    def crashed(self) -> None:
        """Count a question that never produced an answer."""
        self.crashes.inc()

    def render(self) -> bytes:
        """The Prometheus text exposition."""
        return generate_latest(self.registry)
