"""Which guardrail stopped a question, in terms safe to show (no SQL, no database text)."""

from typing import Literal

from pydantic import BaseModel

from text2sql.pipeline.answer import Answer

type GuardrailLayer = Literal["input_rules", "input_classifier", "sql_validator", "database"]


class GuardrailOut(BaseModel):
    """The layer that blocked or rejected the question, and a machine-readable code.

    ``code`` is an input-guard category (``prompt_injection``, ``off_topic``...), a validator
    rule (``read_only``, ``columns``...) or an executor error kind (``QueryPermissionError``).
    """

    layer: GuardrailLayer
    code: str


def guardrail_of(answer: Answer) -> GuardrailOut | None:
    """For ``blocked`` and ``rejected`` answers, the guardrail that stopped them."""
    if answer.status == "blocked":
        for stage in answer.trace.stages:
            if stage.stage == "input_guard":
                layer: GuardrailLayer = (
                    "input_rules" if stage.output.get("layer") == "rules" else "input_classifier"
                )
                return GuardrailOut(layer=layer, code=str(stage.output.get("category", "unknown")))
    if answer.status == "rejected":
        for stage in reversed(answer.trace.stages):
            if stage.status != "error":
                continue
            if stage.stage == "validate":
                return GuardrailOut(layer="sql_validator", code=str(stage.output.get("rule")))
            if stage.stage == "execute":
                return GuardrailOut(layer="database", code=stage.error or "unknown")
    return None
