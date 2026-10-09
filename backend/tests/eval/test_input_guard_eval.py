import pytest

from text2sql.eval import input_guard_eval
from text2sql.eval.input_guard_eval import (
    LabelledQuestion,
    dev_questions,
    held_out_questions,
    score,
)
from text2sql.guard.input_guard import InputVerdict


def _verdict(*, allowed: bool) -> InputVerdict:
    return InputVerdict(
        allowed=allowed,
        category="data_question" if allowed else "prompt_injection",
        reason="r",
        layer="classifier",
    )


def test_score_counts_blocks_false_blocks_and_deeper_attacks() -> None:
    questions = [
        LabelledQuestion("a1", "x", must_block=True),
        LabelledQuestion("a2", "x", must_block=True),
        LabelledQuestion("b1", "x", must_block=False),
        LabelledQuestion("b2", "x", must_block=False),
        LabelledQuestion("d1", "x", must_block=None),
    ]
    verdicts = [_verdict(allowed=a) for a in (False, True, True, False, False)]
    rates = score(questions, verdicts)
    assert (rates.attacks, rates.attacks_blocked, rates.block_rate) == (2, 1, 0.5)
    assert (rates.benign, rates.benign_blocked, rates.false_block_rate) == (2, 1, 0.5)
    assert (rates.missed_attacks, rates.false_blocks) == (("a2",), ("b2",))
    assert (rates.deeper_attacks, rates.deeper_blocked) == (1, 1)


def test_question_sets() -> None:
    test = held_out_questions()
    assert sum(q.must_block is True for q in test) == 44  # input_rules + input_classifier
    assert sum(q.must_block is None for q in test) == 16  # stopped later by design
    assert sum(q.must_block is False for q in test) == 30
    dev = dev_questions()
    assert {q.must_block for q in dev} == {True, False}


async def test_run_once_uses_the_requested_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[str] = []

    async def fake_check(question: str, **kwargs: object) -> InputVerdict:
        del question
        used.append(str(kwargs["prompt_name"]))
        return _verdict(allowed=True)

    monkeypatch.setattr(input_guard_eval, "check_input", fake_check)
    questions = [LabelledQuestion("b1", "x", must_block=False)]
    rates = await input_guard_eval.run_once(
        questions,
        prompt_name="input_guard_v1",
        config=object(),  # type: ignore[arg-type]  # unused by the fake
    )
    assert used == ["input_guard_v1"]
    assert rates.false_block_rate == 0.0
