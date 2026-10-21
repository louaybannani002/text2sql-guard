import itertools
import json
import uuid

from tests.observability.support import answered, attrs, call, stage, typical_answer
from text2sql.observability.langfuse_spans import (
    RequestInfo,
    Span,
    TraceConfig,
    call_cost,
    pseudonym,
    trace_spans,
)

QUERY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
REQUEST = RequestInfo(query_id=QUERY_ID, request_id="req-1", user_id="demo")
CONFIG = TraceConfig(
    environment="test",
    generate_prompt="generate_v2",
    guard_prompt="input_guard_v2",
    free_tier_providers=frozenset({"groq"}),
)


def _spans(config: TraceConfig = CONFIG) -> list[Span]:
    ids = (f"{n:016x}" for n in itertools.count(1))
    return trace_spans(typical_answer(), REQUEST, config, new_span_id=lambda: next(ids))


def _of_type(kind: str, spans: list[Span]) -> list[Span]:
    return [s for s in spans if attrs(s).get("langfuse.observation.type") == kind]


def test_one_root_one_span_per_stage_one_generation_per_call() -> None:
    spans = _spans()
    root, *rest = spans
    assert root["name"] == "query"
    assert "parentSpanId" not in root
    assert {s["traceId"] for s in spans} == {QUERY_ID.hex}
    stages = [s for s in rest if s["parentSpanId"] == root["spanId"]]
    assert [s["name"] for s in stages] == [
        "input_guard",
        "retrieve",
        "generate",
        "validate",
        "generate (retry 1)",
        "validate (retry 1)",
        "execute (retry 1)",
    ]
    assert len(_of_type("generation", spans)) == 4
    assert len({s["spanId"] for s in spans}) == len(spans)


def test_generations_name_the_model_that_answered_and_the_fallback() -> None:
    spans = _spans()
    names = {s["spanId"]: s["name"] for s in spans}
    generations = _of_type("generation", spans)
    fallback = next(g for g in generations if attrs(g)["langfuse.observation.metadata.fallback"])
    values = attrs(fallback)
    assert values["langfuse.observation.model.name"] == "groq/openai/gpt-oss-120b"
    assert values["langfuse.observation.metadata.provider"] == "groq"
    assert values["langfuse.observation.metadata.prompt_version"] == "generate_v2"
    assert json.loads(str(values["langfuse.observation.cost_details"])) == {"total": 0.0}
    assert json.loads(str(values["langfuse.observation.usage_details"])) == {
        "input": 100,
        "output": 20,
        "total": 120,
        "input_cached_tokens": 0,
    }
    assert (values["gen_ai.usage.input_tokens"], values["gen_ai.usage.output_tokens"]) == (100, 20)
    assert names[fallback["parentSpanId"]] == "generate"
    guard = next(g for g in generations if g["name"] == "input_guard.llm")
    assert attrs(guard)["langfuse.observation.metadata.prompt_version"] == "input_guard_v2"
    embedding = next(g for g in generations if g["name"] == "embedding")
    assert "langfuse.observation.cost_details" not in attrs(embedding)  # unknown, not 0


def test_failed_stage_is_an_error_span() -> None:
    validate = next(s for s in _spans() if s["name"] == "validate")
    assert validate["status"] == {"code": 2, "message": "rejected:columns"}
    assert attrs(validate)["langfuse.observation.level"] == "ERROR"


def test_timestamps_follow_the_stage_offsets() -> None:
    spans = {s["name"]: s for s in _spans()}
    start = 1_792_497_600_000_000_000  # 2026-10-20T12:00:00Z
    assert spans["query"]["startTimeUnixNano"] == str(start)
    assert spans["generate"]["startTimeUnixNano"] == str(start + 200_000_000)
    assert spans["generate"]["endTimeUnixNano"] == str(start + 300_000_000)


def test_trace_has_final_sql_prompts_and_totals_but_no_rows_or_personal_data() -> None:
    spans = _spans()
    root = attrs(spans[0])
    output = json.loads(str(root["langfuse.trace.output"]))
    assert output["sql"].startswith("SELECT count(*)")
    assert (output["row_count"], output["columns"]) == (1, ["n"])
    assert root["langfuse.trace.metadata.generate_prompt"] == "generate_v2"
    assert root["langfuse.trace.metadata.request_id"] == "req-1"
    assert root["langfuse.trace.metadata.retries"] == 1
    assert root["langfuse.trace.metadata.fallbacks"] == 1
    assert "langfuse.trace.metadata.total_cost_usd" not in root  # one call has no known price
    assert root["langfuse.user.id"] == pseudonym("demo") != "demo"
    assert root["langfuse.trace.tags"] == ["answered", "test"]
    dumped = json.dumps(spans)
    assert "96478" not in dumped  # result rows never leave
    assert "INTERNAL" not in dumped  # Answer.detail never leaves
    assert '"demo"' not in dumped


def test_question_can_be_left_out() -> None:
    config = TraceConfig("test", "g", "i", capture_question=False)
    root = attrs(_spans(config)[0])
    assert json.loads(str(root["langfuse.trace.input"])) == {
        "question_chars": len(typical_answer().question)
    }


def test_sql_is_only_reported_when_answered() -> None:
    blocked = answered(stage("input_guard")).model_copy(update={"status": "blocked"})
    root = attrs(trace_spans(blocked, REQUEST, CONFIG)[0])
    assert json.loads(str(root["langfuse.trace.output"]))["sql"] is None


def test_free_tier_cost_is_zero_and_unknown_stays_unknown() -> None:
    free = frozenset({"gemini"})
    assert call_cost(call("gemini/flash", cost=0.5), free) == 0.0
    assert call_cost(call("openai/gpt-5.4", cost=0.5), free) == 0.5
    assert call_cost(call("groq/x", cost=None), free) is None
