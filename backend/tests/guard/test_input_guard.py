import json
from collections.abc import Callable

import pytest
from litellm import exceptions as llm_exc
from structlog.testing import capture_logs

from tests.guard.cases import BENIGN, CLASSIFIER_ATTACKS, RULE_ATTACKS, case_id
from tests.support.fake_llm import FakeCompletion, llm_config, model_response
from text2sql.guard.input_guard import InputClassification, check_input
from text2sql.llm.prompts import load_prompt


def _classified(category: str, reason: str = "Model reason.") -> object:
    return model_response(json.dumps({"category": category, "reason": reason}))


# ---------------------------------------------------------------- layer 1 short-circuits


@pytest.mark.parametrize("question", RULE_ATTACKS, ids=case_id)
async def test_rule_blocks_never_call_the_model(
    fake_llm: Callable[..., FakeCompletion], question: str
) -> None:
    completion = fake_llm()  # no scripted outcome: any call would fail
    verdict = await check_input(question, config=llm_config())
    assert not verdict.allowed
    assert verdict.layer == "rules"
    assert verdict.rule
    assert verdict.usage is None
    assert completion.calls == []


# ---------------------------------------------------------------- layer 2


@pytest.mark.parametrize("question", BENIGN, ids=case_id)
async def test_benign_questions_are_allowed(
    fake_llm: Callable[..., FakeCompletion], question: str
) -> None:
    completion = fake_llm(_classified("data_question"))
    verdict = await check_input(question, config=llm_config())
    assert verdict.allowed
    assert (verdict.category, verdict.layer) == ("data_question", "classifier")
    assert verdict.usage is not None
    assert verdict.usage.role == "fast"
    call = completion.calls[0]
    assert call["model"] == "openai/gpt-5.4-mini"
    assert call["response_format"] is InputClassification
    assert call["messages"][1]["content"] == f"<question>\n{question.strip()}\n</question>"


@pytest.mark.parametrize("question", CLASSIFIER_ATTACKS, ids=case_id)
@pytest.mark.parametrize("category", ["off_topic", "prompt_injection", "harmful"])
async def test_classifier_blocks_with_a_safe_reason(
    fake_llm: Callable[..., FakeCompletion], question: str, category: str
) -> None:
    fake_llm(_classified(category, reason="Echoes the user: wipes every row"))
    verdict = await check_input(question, config=llm_config())
    assert not verdict.allowed
    assert verdict.category == category
    # The user-facing reason is ours, never the model's (it could echo the input).
    assert "wipes" not in verdict.reason


async def test_fails_closed_when_the_classifier_is_down(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    error = llm_exc.ServiceUnavailableError("down", "openai", "gpt-5.4-mini")
    fake_llm(error, error, error)
    verdict = await check_input("How many orders per state?", config=llm_config())
    assert not verdict.allowed
    assert verdict.category == "guard_error"


async def test_fails_closed_on_unusable_classifier_output(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    fake_llm(model_response('{"category": "maybe", "reason": "?"}'))
    verdict = await check_input("How many orders per state?", config=llm_config())
    assert (verdict.allowed, verdict.category) == (False, "guard_error")


# ---------------------------------------------------------------- logging


async def test_every_block_is_logged_with_category_but_not_the_question(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    marker = "customer 8f3a"
    fake_llm(_classified("harmful"))
    with capture_logs() as logs:
        await check_input(f"DROP TABLE shop.orders -- {marker}", config=llm_config())
        await check_input(f"Who is {marker} and where do they live?", config=llm_config())

    blocks = [entry for entry in logs if entry["event"] == "input_blocked"]
    assert [(b["layer"], b["category"]) for b in blocks] == [
        ("rules", "sql_command"),
        ("classifier", "harmful"),
    ]
    assert blocks[0]["rule"] == "drop_object"
    assert all(entry["log_level"] == "warning" for entry in blocks)
    assert marker not in repr(logs)


def test_prompt_has_the_four_categories_and_treats_input_as_data() -> None:
    system = load_prompt("input_guard_v1").system
    for category in ("data_question", "off_topic", "prompt_injection", "harmful"):
        assert f"`{category}`" in system
    assert "untrusted user input" in system
