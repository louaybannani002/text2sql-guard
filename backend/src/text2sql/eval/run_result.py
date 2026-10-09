"""One evaluation run: what was evaluated, its metrics and the per-question outcomes."""

from collections.abc import Sequence
from dataclasses import dataclass

from text2sql.eval.metrics import EvalMetrics
from text2sql.eval.outcomes import AttackOutcome, BenignOutcome, GoldOutcome


@dataclass(frozen=True)
class RunInfo:
    """What was evaluated, with what."""

    date: str
    choice: str  # "main" / "local"
    model: str
    guard_model: str
    prompts: dict[str, str]
    datasets: dict[str, int]
    cache: bool
    smoke: bool
    git_commit: str
    duration_s: float


@dataclass(frozen=True)
class RunResult:
    """One evaluation run: its metadata, metrics and per-question outcomes."""

    info: RunInfo
    metrics: EvalMetrics
    gold: Sequence[GoldOutcome] = ()
    attacks: Sequence[AttackOutcome] = ()
    benign: Sequence[BenignOutcome] = ()
