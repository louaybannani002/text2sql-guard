"""The 20-question smoke subset (eval/datasets/smoke.json) and the thresholds CI enforces."""

import json
from dataclasses import dataclass
from pathlib import Path

from text2sql.eval.datasets import DATASETS_DIR, Attack, GoldPair
from text2sql.eval.metrics import EvalMetrics


@dataclass(frozen=True)
class SmokeSpec:
    """Which questions form the subset, and the minimum scores."""

    gold_ids: list[str]
    attack_ids: list[str]
    min_execution_accuracy: float
    min_attack_block_rate: float


def load_smoke(directory: Path = DATASETS_DIR) -> SmokeSpec:
    """Read ``smoke.json``."""
    raw = json.loads((directory / "smoke.json").read_text(encoding="utf-8"))
    thresholds = raw["thresholds"]
    return SmokeSpec(
        gold_ids=list(raw["gold"]),
        attack_ids=list(raw["adversarial"]),
        min_execution_accuracy=float(thresholds["execution_accuracy"]),
        min_attack_block_rate=float(thresholds["attack_block_rate"]),
    )


def select[T: (GoldPair, Attack)](items: list[T], ids: list[str]) -> list[T]:
    """The items with these ids, in the order given; unknown ids are an error."""
    by_id = {item.id: item for item in items}
    missing = [i for i in ids if i not in by_id]
    if missing:
        msg = f"smoke.json lists unknown ids: {missing}"
        raise ValueError(msg)
    return [by_id[i] for i in ids]


def threshold_failures(metrics: EvalMetrics, spec: SmokeSpec) -> list[str]:
    """Human-readable violations; empty when the run passes."""
    problems: list[str] = []
    if metrics.infrastructure_errors:
        problems.append(
            f"{len(metrics.infrastructure_errors)} questions hit provider errors after retries: "
            "the run cannot be trusted"
        )
    accuracy = metrics.gold.execution_accuracy.rate if metrics.gold else None
    if accuracy is None or accuracy < spec.min_execution_accuracy:
        problems.append(
            f"execution accuracy {accuracy if accuracy is None else f'{accuracy:.1%}'} "
            f"< {spec.min_execution_accuracy:.0%}"
        )
    blocked = metrics.attacks.blocked.rate if metrics.attacks else None
    if blocked is None or blocked < spec.min_attack_block_rate:
        problems.append(
            f"attack block rate {blocked if blocked is None else f'{blocked:.1%}'} "
            f"< {spec.min_attack_block_rate:.0%}"
        )
    return problems
