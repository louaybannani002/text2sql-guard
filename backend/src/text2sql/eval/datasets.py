"""Typed loaders for the evaluation datasets in ``eval/datasets/`` (JSON Lines).

- ``gold.jsonl``: question / gold SQL pairs, tagged by category and difficulty.
- ``adversarial.jsonl``: attacks, each with the first layer expected to stop it.
- ``benign_tricky.jsonl``: legitimate questions that look suspicious (false-block rate).
- ``classifier_dev.jsonl``: benign and attack examples for tuning the input classifier prompt;
  kept apart from the two test sets above so they measure prompts honestly.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DATASETS_DIR = Path(__file__).resolve().parents[4] / "eval" / "datasets"

type Category = Literal["sales", "delivery", "reviews", "sellers", "products"]
type Difficulty = Literal["easy", "medium", "hard"]
type AttackCategory = Literal[
    "destructive_sql", "prompt_injection", "personal_data", "resource_exhaustion", "obfuscated"
]
# Pipeline order. "generator": restricted data is not in the model's schema, so it must answer
# cannot_answer or use opaque keys only.
type Layer = Literal[
    "input_rules", "input_classifier", "generator", "sql_validator", "executor", "database"
]
LAYER_ORDER: tuple[Layer, ...] = (
    "input_rules",
    "input_classifier",
    "generator",
    "sql_validator",
    "executor",
    "database",
)


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldPair(_Record):
    """A question and the SQL that answers it on the Olist schema.

    ``tables`` is what the validator reports for ``sql``; ``review`` explains why the question
    is ambiguous and needs a human decision (None when it is not).
    """

    id: str
    category: Category
    difficulty: Difficulty
    question: str = Field(min_length=10)
    sql: str
    tables: list[str] = Field(min_length=1)
    assumptions: list[str]
    review: str | None


class Attack(_Record):
    """An attack and the first layer that must stop it.

    ``sql`` is what a manipulated or buggy generator could emit; ``sql_blocked_by`` lists the
    layers that must each stop that SQL on their own (defense in depth).
    """

    id: str
    category: AttackCategory
    technique: str
    question: str
    expected_layer: Layer
    sql: str | None
    sql_blocked_by: list[Layer]
    validator_rule: str | None = None


class BenignCase(_Record):
    """A legitimate question that must not be blocked.

    ``known_false_block`` ("<layer>:<rule>") documents a block that happens today and is
    accepted for now; it makes the false-block rate honest instead of hiding the case.
    """

    id: str
    question: str
    why_tricky: str
    expected_status: Literal["answered", "cannot_answer"]
    known_false_block: str | None


class ClassifierDevCase(_Record):
    """A labelled example for tuning the classifier prompt (never used to report results)."""

    id: str
    label: Literal["benign", "attack"]
    question: str
    note: str


def _load[T: _Record](model: type[T], path: Path) -> list[T]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [model.model_validate_json(line) for line in lines if line.strip()]


def load_gold(directory: Path = DATASETS_DIR) -> list[GoldPair]:
    """All gold pairs."""
    return _load(GoldPair, directory / "gold.jsonl")


def load_adversarial(directory: Path = DATASETS_DIR) -> list[Attack]:
    """All attacks."""
    return _load(Attack, directory / "adversarial.jsonl")


def load_benign_tricky(directory: Path = DATASETS_DIR) -> list[BenignCase]:
    """All benign-but-suspicious questions."""
    return _load(BenignCase, directory / "benign_tricky.jsonl")


def load_classifier_dev(directory: Path = DATASETS_DIR) -> list[ClassifierDevCase]:
    """The classifier tuning set."""
    return _load(ClassifierDevCase, directory / "classifier_dev.jsonl")


def needs_review(pairs: Sequence[GoldPair]) -> list[GoldPair]:
    """Gold pairs whose meaning is ambiguous and awaits a human decision."""
    return [pair for pair in pairs if pair.review]
