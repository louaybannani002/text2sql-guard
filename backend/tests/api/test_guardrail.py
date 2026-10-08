import pytest

from tests.api.conftest import make_answer
from text2sql.api.guardrail import GuardrailOut, guardrail_of
from text2sql.executor.serialize import JsonValue
from text2sql.pipeline.trace import StageTrace, Trace


def _stage(
    stage: str,
    status: str = "ok",
    output: dict[str, JsonValue] | None = None,
    error: str | None = None,
) -> StageTrace:
    return StageTrace(
        stage=stage,  # type: ignore[arg-type]  # parametrised stage names
        attempt=1,
        status=status,  # type: ignore[arg-type]
        latency_ms=1.0,
        input={},
        output=output or {},
        tokens=0,
        cost_usd=0.0,
        error=error,
    )


def _trace(*stages: StageTrace) -> Trace:
    return Trace(stages=list(stages), total_ms=10.0)


@pytest.mark.parametrize(
    ("layer", "expected"), [("rules", "input_rules"), ("classifier", "input_classifier")]
)
def test_blocked_by_the_input_guard(layer: str, expected: str) -> None:
    trace = _trace(
        _stage(
            "input_guard",
            "error",
            {"allowed": False, "category": "prompt_injection", "layer": layer},
        )
    )
    answer = make_answer("q", status="blocked", result=None, trace=trace)
    assert guardrail_of(answer) == GuardrailOut(layer=expected, code="prompt_injection")  # type: ignore[arg-type]


def test_rejected_by_the_sql_validator() -> None:
    trace = _trace(
        _stage("input_guard"),
        _stage("validate", "error", {"valid": False, "rule": "read_only", "security": True}),
    )
    answer = make_answer("q", status="rejected", result=None, trace=trace)
    assert guardrail_of(answer) == GuardrailOut(layer="sql_validator", code="read_only")


def test_rejected_by_database_permissions() -> None:
    trace = _trace(
        _stage("input_guard"),
        _stage("validate", "ok", {"valid": True}),
        _stage("execute", "error", error="QueryPermissionError"),
    )
    answer = make_answer("q", status="rejected", result=None, trace=trace)
    assert guardrail_of(answer) == GuardrailOut(layer="database", code="QueryPermissionError")


@pytest.mark.parametrize("status", ["answered", "failed", "cannot_answer"])
def test_other_statuses_have_no_guardrail(status: str) -> None:
    assert guardrail_of(make_answer("q", status=status)) is None
