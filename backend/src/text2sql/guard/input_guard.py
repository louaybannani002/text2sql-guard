"""Input guard: decide whether a user question may enter the pipeline.

Layer 1: deterministic rules (``input_rules``), no cost. Layer 2: the ``fast`` model classifies
the question; it runs only if layer 1 lets the question through. Fails closed: if the
classifier cannot be reached, the question is blocked.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from text2sql.guard.input_rules import RuleCategory, check_rules
from text2sql.llm import LLMConfig, LLMError, Message, generate_structured
from text2sql.llm.prompts import load_prompt
from text2sql.llm.types import Usage
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

PROMPT_NAME = "input_guard_v2"

type ClassifierCategory = Literal["data_question", "off_topic", "prompt_injection", "harmful"]
type InputCategory = ClassifierCategory | RuleCategory | Literal["guard_error"]

_MESSAGES: dict[str, str] = {
    "off_topic": "I can only answer questions about the marketplace data.",
    "prompt_injection": "The question tries to change how the assistant works.",
    "harmful": "The question asks for personal data or could cause harm.",
    "guard_error": "The question could not be checked right now; please try again.",
}


class InputClassification(BaseModel):
    """Layer-2 output schema."""

    model_config = ConfigDict(frozen=True)

    category: ClassifierCategory
    reason: str = Field(description="One short sentence; never quote the user's text.")


class InputVerdict(BaseModel):
    """Whether a question may proceed, and why."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    category: InputCategory
    reason: str = Field(description="Safe to show to the user.")
    layer: Literal["rules", "classifier"]
    rule: str | None = Field(default=None, description="Layer-1 rule that fired, if any.")
    usage: Usage | None = Field(default=None, description="Classifier call; None for layer 1.")


def _messages(question: str, prompt_name: str) -> list[Message]:
    prompt = load_prompt(prompt_name)
    return [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.render_user(question=question.strip())},
    ]


def _blocked(verdict: InputVerdict, length: int) -> InputVerdict:
    # Never log the question itself: it is untrusted and may contain personal data.
    log.warning(
        "input_blocked",
        layer=verdict.layer,
        category=verdict.category,
        rule=verdict.rule,
        question_length=length,
    )
    return verdict


async def check_input(
    question: str, *, config: LLMConfig | None = None, prompt_name: str = PROMPT_NAME
) -> InputVerdict:
    """Screen ``question`` before any retrieval or generation happens.

    Args:
        question: Raw user input.
        config: LLM configuration override (tests); defaults to the application settings.
        prompt_name: Classifier prompt version; only evaluations compare other versions.
    """
    hit = check_rules(question)
    if hit is not None:
        verdict = InputVerdict(
            allowed=False, category=hit.category, reason=hit.reason, layer="rules", rule=hit.rule
        )
        return _blocked(verdict, len(question))

    try:
        result = await generate_structured(
            _messages(question, prompt_name), InputClassification, "fast", config=config
        )
    except LLMError as exc:
        log.error("input_guard_unavailable", error=type(exc).__name__)  # noqa: TRY400 - no trace needed
        verdict = InputVerdict(
            allowed=False,
            category="guard_error",
            reason=_MESSAGES["guard_error"],
            layer="classifier",
        )
        return _blocked(verdict, len(question))

    category = result.output.category
    verdict = InputVerdict(
        allowed=category == "data_question",
        category=category,
        reason=result.output.reason if category == "data_question" else _MESSAGES[category],
        layer="classifier",
        usage=result.usage,
    )
    if not verdict.allowed:
        return _blocked(verdict, len(question))
    log.info("input_allowed", layer="classifier", cost_usd=result.usage.cost_usd)
    return verdict
