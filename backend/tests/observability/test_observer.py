import uuid
from collections.abc import Sequence

import pytest

from tests.observability.support import FakeSink, typical_answer
from text2sql.config.settings import Settings
from text2sql.observability.langfuse_client import LangfuseSink, NoopSink
from text2sql.observability.langfuse_spans import RequestInfo, Span
from text2sql.observability.observer import Observer, build_observer, langfuse_sink

REQUEST = RequestInfo(query_id=uuid.uuid4(), request_id="r", user_id="demo")


def _with(settings: Settings, **update: object) -> Settings:
    return settings.model_copy(update=update)


async def test_tracing_needs_the_flag_and_all_three_values(settings: Settings) -> None:
    enabled = _with(settings, langfuse_enabled=True)
    real = langfuse_sink(enabled)
    assert isinstance(real, LangfuseSink)
    await real.aclose()
    assert isinstance(langfuse_sink(settings), NoopSink)  # LANGFUSE_ENABLED=false in tests
    for missing in ("langfuse_public_key", "langfuse_secret_key", "langfuse_host"):
        assert isinstance(langfuse_sink(_with(enabled, **{missing: None})), NoopSink)


def test_metrics_can_be_turned_off(settings: Settings) -> None:
    on = build_observer(settings, generate_prompt="generate_v2", guard_prompt="input_guard_v2")
    off = build_observer(
        _with(settings, metrics_enabled=False), generate_prompt="g", guard_prompt="i"
    )
    assert on.metrics is not None
    assert off.metrics is None
    assert not on.tracing


async def test_record_traces_and_counts(settings: Settings) -> None:
    sink = FakeSink()
    observer = build_observer(
        _with(settings, llm_free_tier_providers=["Groq"]),
        generate_prompt="generate_v2",
        guard_prompt="input_guard_v2",
        sink=sink,
    )
    observer.record(typical_answer(), REQUEST)
    observer.record(None, REQUEST)  # a crash is counted, not traced
    await observer.aclose()
    (batch,) = sink.batches
    assert batch[0]["name"] == "query"
    assert batch[0]["traceId"] == REQUEST.query_id.hex
    assert observer.config.free_tier_providers == frozenset({"groq"})
    assert observer.metrics is not None
    assert observer.metrics.registry.get_sample_value("t2s_query_crashes_total") == 1
    assert sink.closed


def test_record_never_raises(capsys: pytest.CaptureFixture[str]) -> None:
    class Exploding(FakeSink):
        def submit(self, spans: Sequence[Span]) -> None:
            raise RuntimeError(str(spans))

    observer = Observer(Observer.disabled().config, sink=Exploding(), metrics=None)
    observer.record(typical_answer(), REQUEST)
    out = capsys.readouterr().out
    assert "observe_failed" in out
    assert "How many orders" not in out
