"""Block and false-block rates of the input guard (rules + classifier) over labelled questions.

``python -m text2sql.eval.input_guard_eval --prompt input_guard_v2 --runs 3 --set test``
(``--set dev`` for the tuning set). Calls the real classifier: needs OPENAI_API_KEY; about
$0.05 per run over the test sets. Prints rates only, never the questions.
"""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from text2sql.config.settings import get_settings
from text2sql.eval.datasets import load_adversarial, load_benign_tricky, load_classifier_dev
from text2sql.guard.input_guard import PROMPT_NAME, InputVerdict, check_input
from text2sql.llm import LLMConfig

# Attacks the input guard is responsible for; deeper ones are stopped later by design.
INPUT_LAYERS = frozenset({"input_rules", "input_classifier"})


@dataclass(frozen=True, slots=True)
class LabelledQuestion:
    """A question and whether the input guard must block it (None: not its job)."""

    id: str
    text: str
    must_block: bool | None


@dataclass(frozen=True, slots=True)
class RunRates:
    """One pass over the questions."""

    attacks: int
    attacks_blocked: int
    benign: int
    benign_blocked: int
    false_blocks: tuple[str, ...]
    missed_attacks: tuple[str, ...]
    deeper_attacks: int = 0  # stopped by later layers by design; blocking early is a bonus
    deeper_blocked: int = 0

    @property
    def block_rate(self) -> float:
        """Share of must-block attacks that were blocked."""
        return self.attacks_blocked / self.attacks if self.attacks else 1.0

    @property
    def false_block_rate(self) -> float:
        """Share of benign questions that were blocked."""
        return self.benign_blocked / self.benign if self.benign else 0.0


def held_out_questions() -> list[LabelledQuestion]:
    """adversarial.jsonl + benign_tricky.jsonl."""
    attacks = [
        LabelledQuestion(a.id, a.question, a.expected_layer in INPUT_LAYERS or None)
        for a in load_adversarial()
    ]
    benign = [LabelledQuestion(b.id, b.question, must_block=False) for b in load_benign_tricky()]
    return attacks + benign


def dev_questions() -> list[LabelledQuestion]:
    """classifier_dev.jsonl."""
    return [
        LabelledQuestion(c.id, c.question, must_block=c.label == "attack")
        for c in load_classifier_dev()
    ]


def score(questions: Sequence[LabelledQuestion], verdicts: Sequence[InputVerdict]) -> RunRates:
    """Rates for one run; questions with ``must_block=None`` are ignored."""
    pairs = list(zip(questions, verdicts, strict=True))
    attacks = [(q, v) for q, v in pairs if q.must_block is True]
    benign = [(q, v) for q, v in pairs if q.must_block is False]
    deeper = [(q, v) for q, v in pairs if q.must_block is None]
    return RunRates(
        attacks=len(attacks),
        attacks_blocked=sum(not v.allowed for _, v in attacks),
        benign=len(benign),
        benign_blocked=sum(not v.allowed for _, v in benign),
        false_blocks=tuple(q.id for q, v in benign if not v.allowed),
        missed_attacks=tuple(q.id for q, v in attacks if v.allowed),
        deeper_attacks=len(deeper),
        deeper_blocked=sum(not v.allowed for _, v in deeper),
    )


async def run_once(
    questions: Sequence[LabelledQuestion],
    *,
    prompt_name: str,
    config: LLMConfig,
    concurrency: int = 5,
) -> RunRates:
    """Screen every question once with ``prompt_name`` and score the run."""
    limit = asyncio.Semaphore(concurrency)

    async def one(question: LabelledQuestion) -> InputVerdict:
        async with limit:
            return await check_input(question.text, config=config, prompt_name=prompt_name)

    verdicts = await asyncio.gather(*(one(q) for q in questions))
    return score(questions, verdicts)


async def _main(prompt_name: str, runs: int, which: str) -> None:
    config = LLMConfig.from_settings(get_settings())
    questions = dev_questions() if which == "dev" else held_out_questions()
    for run in range(1, runs + 1):
        rates = await run_once(questions, prompt_name=prompt_name, config=config)
        print(  # noqa: T201 - command-line report
            f"{prompt_name} {which} run {run}: "
            f"attacks blocked {rates.attacks_blocked}/{rates.attacks} ({rates.block_rate:.0%}), "
            f"false blocks {rates.benign_blocked}/{rates.benign} ({rates.false_block_rate:.1%}) "
            f"{list(rates.false_blocks)} missed {list(rates.missed_attacks)}; "
            f"deeper-layer attacks already blocked {rates.deeper_blocked}/{rates.deeper_attacks}"
        )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.eval.input_guard_eval")
    parser.add_argument("--prompt", default=PROMPT_NAME)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--set", choices=["test", "dev"], default="test", dest="which")
    args = parser.parse_args()
    asyncio.run(_main(args.prompt, args.runs, args.which))


if __name__ == "__main__":
    main()
