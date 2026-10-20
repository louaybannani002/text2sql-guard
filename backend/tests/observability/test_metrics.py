from prometheus_client import CollectorRegistry

from tests.observability.support import answered, call, stage, typical_answer
from text2sql.observability.metrics import PipelineMetrics


def _metrics() -> PipelineMetrics:
    return PipelineMetrics(CollectorRegistry(), free_tier_providers=frozenset({"gemini"}))


def _value(metrics: PipelineMetrics, name: str, **labels: str) -> float:
    value = metrics.registry.get_sample_value(name, labels)
    return value if value is not None else 0.0


def test_counts_queries_stages_retries_fallbacks_and_cost() -> None:
    metrics = _metrics()
    metrics.observe(typical_answer(), guard_layer=None)
    assert _value(metrics, "t2s_queries_total", status="answered") == 1
    assert _value(metrics, "t2s_stages_total", stage="generate", status="ok") == 2
    assert _value(metrics, "t2s_stages_total", stage="validate", status="error") == 1
    assert _value(metrics, "t2s_stage_duration_seconds_count", stage="generate") == 2
    assert _value(metrics, "t2s_query_duration_seconds_sum") == 0.9
    assert _value(metrics, "t2s_generation_retries_total") == 1
    assert (
        _value(
            metrics,
            "t2s_llm_fallbacks_total",
            role="main",
            provider="groq",
            model="groq/openai/gpt-oss-120b",
        )
        == 1
    )
    assert _value(metrics, "t2s_llm_cost_usd_total", provider="gemini") == 0.0  # free tier
    assert _value(metrics, "t2s_llm_tokens_total", provider="gemini", model="gemini/flash") == 120


def test_paid_cost_accumulates_and_unknown_cost_is_skipped() -> None:
    metrics = _metrics()
    paid = answered(stage("generate", calls=[call("openai/gpt-5.4", cost=0.25)]), attempts=1)
    for _ in range(2):
        metrics.observe(paid, guard_layer=None)
    metrics.observe(
        answered(stage("generate", calls=[call("groq/x", cost=None)]), attempts=1),
        guard_layer=None,
    )
    assert _value(metrics, "t2s_llm_cost_usd_total", provider="openai") == 0.5
    assert _value(metrics, "t2s_llm_cost_usd_total", provider="groq") == 0.0
    assert _value(metrics, "t2s_generation_retries_total") == 0


def test_guard_blocks_cache_hits_and_crashes() -> None:
    metrics = _metrics()
    blocked = answered(stage("input_guard", status="error"), attempts=0)
    metrics.observe(blocked.model_copy(update={"status": "blocked"}), guard_layer="input_rules")
    metrics.observe(answered(stage("cache"), cache="exact", attempts=0), guard_layer=None)
    metrics.crashed()
    assert _value(metrics, "t2s_guard_blocks_total", layer="input_rules") == 1
    assert _value(metrics, "t2s_queries_total", status="blocked") == 1
    assert _value(metrics, "t2s_cache_hits_total", level="exact") == 1
    assert _value(metrics, "t2s_query_crashes_total") == 1


def test_render_is_prometheus_text_without_question_or_sql() -> None:
    metrics = _metrics()
    metrics.observe(typical_answer(), guard_layer=None)
    text = metrics.render().decode()
    assert "# TYPE t2s_queries_total counter" in text
    assert "delivered" not in text
    assert "SELECT" not in text
