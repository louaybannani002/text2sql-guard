"""The fixed gold subset used to compare prompts on a free-tier token budget.

The subset is chosen by a rule, never by hand: per difficulty, the questions whose id has the
smallest SHA-256 hash, in the full set's proportions (18 easy, 24 medium, 18 hard of 45/60/45).
Nobody reads the questions or past results to pick them, so the subset cannot be tuned to a
prompt. ``eval/datasets/compare_subset.json`` stores the ids; a test checks it follows the rule.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from text2sql.eval.datasets import DATASETS_DIR, GoldPair

SUBSET_FILE = DATASETS_DIR / "compare_subset.json"
PER_DIFFICULTY: Mapping[str, int] = {"easy": 18, "medium": 24, "hard": 18}


def _rank(question_id: str) -> str:
    return hashlib.sha256(question_id.encode()).hexdigest()


def stratified_ids(
    gold: Sequence[GoldPair], per_difficulty: Mapping[str, int] = PER_DIFFICULTY
) -> list[str]:
    """The subset's ids, in dataset order."""
    chosen: set[str] = set()
    for difficulty, n in per_difficulty.items():
        pool = sorted((g.id for g in gold if g.difficulty == difficulty), key=_rank)
        if len(pool) < n:
            msg = f"only {len(pool)} {difficulty} questions, {n} requested"
            raise ValueError(msg)
        chosen.update(pool[:n])
    return [g.id for g in gold if g.id in chosen]


def load_subset_ids(path: Path = SUBSET_FILE) -> list[str]:
    """The ids stored in ``compare_subset.json``."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [str(i) for i in raw["gold"]]
