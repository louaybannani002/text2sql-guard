"""What happened to each evaluated question, and which layer stopped it."""

from dataclasses import dataclass, field
from typing import Literal

from text2sql.executor.serialize import JsonValue
from text2sql.pipeline.answer import Answer

type StopLayer = Literal[
    "input_rules", "input_classifier", "generator", "sql_validator", "executor", "database"
]
_EXECUTOR_LIMITS = frozenset({"QueryTooExpensiveError", "QueryTimeoutError"})
# Provider trouble (rate limits, outages, timeouts), not a verdict on the question. Malformed
# model output (LLMOutputValidationError) is a model-quality result and is NOT in this set.
_TRANSIENT = frozenset({"LLMTimeoutError", "LLMProviderError"})


def infrastructure_error(answer: Answer) -> bool:
    """The answer reflects an outage, not the pipeline's judgement: retry or exclude it."""
    if answer.status == "blocked":
        guard = next((s for s in answer.trace.stages if s.stage == "input_guard"), None)
        return guard is not None and guard.output.get("category") == "guard_error"
    if answer.status == "failed":
        if not answer.trace.stages:
            return True  # the evaluation itself crashed on this question
        return any(s.error in _TRANSIENT for s in answer.trace.stages if s.status == "error")
    return False


def stopped_by(answer: Answer) -> StopLayer | Literal["failed"] | None:
    """The guardrail that stopped the question; None if answered, "failed" on other errors."""
    if answer.status == "answered":
        return None
    if answer.status == "blocked":
        guard = next((s for s in answer.trace.stages if s.stage == "input_guard"), None)
        layer = guard.output.get("layer") if guard else None
        return "input_rules" if layer == "rules" else "input_classifier"
    if answer.status == "cannot_answer":
        return "generator"
    errors = [s for s in answer.trace.stages if s.status == "error"]
    last = errors[-1] if errors else None
    if answer.status == "rejected":
        return "sql_validator" if last is not None and last.stage == "validate" else "database"
    if last is not None and last.stage == "execute" and last.error in _EXECUTOR_LIMITS:
        return "executor"
    return "failed"


@dataclass(frozen=True)
class Usage:
    """Cost of one pipeline run."""

    total_ms: float
    tokens: int
    cost_usd: float | None
    cache: str | None  # "exact" / "semantic" / None

    @classmethod
    def of(cls, answer: Answer) -> "Usage":
        """From the answer's trace."""
        trace = answer.trace
        return cls(trace.total_ms, trace.total_tokens, trace.total_cost_usd, answer.cache)


@dataclass(frozen=True)
class GoldOutcome:
    """A gold question: did the predicted result equal the gold result?"""

    id: str
    category: str
    difficulty: str
    question: str
    status: str
    correct: bool
    reason: str
    predicted_sql: str | None
    gold_sql: str
    usage: Usage
    message: str = ""
    detail: str | None = None
    infra_error: bool = False
    predicted_columns: list[str] = field(default_factory=list)
    predicted_sample: list[list[JsonValue]] = field(default_factory=list)
    gold_columns: list[str] = field(default_factory=list)
    gold_sample: list[list[JsonValue]] = field(default_factory=list)

    @property
    def valid_sql(self) -> bool:
        """The pipeline produced SQL that passed the validator and executed."""
        return self.status == "answered"


@dataclass(frozen=True)
class AttackOutcome:
    """An attack: which layer stopped it (None = answered, read-only and validated)."""

    id: str
    category: str
    technique: str
    expected_layer: str
    status: str
    stopped_by: str | None
    usage: Usage
    predicted_sql: str | None = None
    infra_error: bool = False

    @property
    def blocked(self) -> bool:
        """Stopped by a guardrail (a pipeline failure is not counted as a block)."""
        return self.stopped_by not in {None, "failed"}


@dataclass(frozen=True)
class BenignOutcome:
    """A legitimate question: was it blocked anyway?"""

    id: str
    expected_status: str
    known_false_block: str | None
    status: str
    stopped_by: str | None
    usage: Usage
    infra_error: bool = False

    @property
    def false_block(self) -> bool:
        """Blocked by the input guard, or rejected by a later guardrail."""
        return self.status in {"blocked", "rejected"}


type Outcome = GoldOutcome | AttackOutcome | BenignOutcome
