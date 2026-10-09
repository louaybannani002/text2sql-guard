import pytest

from tests.eval.support import answer, attack, benign, stage
from text2sql.eval.outcomes import Usage, infrastructure_error, stopped_by
from text2sql.pipeline.answer import Answer


@pytest.mark.parametrize(
    ("result", "layer"),
    [
        (answer("answered"), None),
        (answer("blocked", stage("input_guard", "error", {"layer": "rules"})), "input_rules"),
        (
            answer("blocked", stage("input_guard", "error", {"layer": "classifier"})),
            "input_classifier",
        ),
        (answer("cannot_answer", stage("generate")), "generator"),
        (answer("rejected", stage("validate", "error", error="rejected:columns")), "sql_validator"),
        (
            answer(
                "rejected",
                stage("validate"),
                stage("execute", "error", error="QueryPermissionError"),
            ),
            "database",
        ),
        (answer("failed", stage("execute", "error", error="QueryTooExpensiveError")), "executor"),
        (answer("failed", stage("execute", "error", error="QueryTimeoutError")), "executor"),
        (answer("failed", stage("generate", "error", error="LLMTimeoutError")), "failed"),
        (answer("failed"), "failed"),
    ],
)
def test_stopped_by(result: Answer, layer: str | None) -> None:
    assert stopped_by(result) == layer


def test_usage_from_the_trace() -> None:
    result = answer("answered", stage("generate", tokens=50), cache="exact", total_ms=320.0)
    assert Usage.of(result) == Usage(total_ms=320.0, tokens=50, cost_usd=0.001, cache="exact")


def test_block_flags() -> None:
    assert attack("a", "input_rules").blocked
    assert not attack("a", None).blocked
    assert not attack("a", "failed").blocked
    assert benign("b", "blocked").false_block
    assert benign("b", "rejected").false_block
    assert not benign("b", "cannot_answer").false_block


@pytest.mark.parametrize(
    ("result", "outage"),
    [
        (answer("blocked", stage("input_guard", "error", {"category": "guard_error"})), True),
        (answer("blocked", stage("input_guard", "error", {"category": "prompt_injection"})), False),
        (answer("failed", stage("retrieve", "error", error="LLMProviderError")), True),
        (answer("failed", stage("generate", "error", error="LLMTimeoutError")), True),
        (answer("failed", stage("generate", "error", error="LLMOutputValidationError")), False),
        (answer("failed", stage("execute", "error", error="QueryTimeoutError")), False),
        (answer("failed"), True),  # the evaluation itself crashed
        (answer("answered"), False),
    ],
)
def test_infrastructure_error(result: Answer, outage: bool) -> None:  # noqa: FBT001 - parametrised
    assert infrastructure_error(result) is outage
