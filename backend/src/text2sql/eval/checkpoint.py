"""Resumable runs: each finished question is appended to ``runs/<run name>/outcomes.jsonl``.

A run interrupted by free-tier limits (circuit breaker, exit code 3) or by the user continues
where it stopped when started again with the same run name. Questions that ended in an
infrastructure error are not treated as done: they are asked again.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from text2sql.eval.outcomes import AttackOutcome, BenignOutcome, GoldOutcome, Outcome, Usage
from text2sql.eval.report import jsonable_dict

type Dataset = Literal["gold", "adversarial", "benign"]
_TYPES: dict[str, type[GoldOutcome] | type[AttackOutcome] | type[BenignOutcome]] = {
    "gold": GoldOutcome,
    "adversarial": AttackOutcome,
    "benign": BenignOutcome,
}


def _decode(dataset: str, raw: dict[str, object]) -> Outcome:
    usage = raw["usage"]
    assert isinstance(usage, dict)  # noqa: S101 - written by encode below
    usage = {
        **usage,
        "sql_models": tuple(usage.get("sql_models", ())),
    }  # JSON list; absent in old runs
    return _TYPES[dataset](**{**raw, "usage": Usage(**usage)})  # type: ignore[arg-type]  # fields as written by jsonable_dict


@dataclass(frozen=True)
class Checkpoint:
    """The outcome log of one named run."""

    path: Path

    @classmethod
    def open(cls, directory: Path, run_name: str, *, fresh: bool = False) -> "Checkpoint":
        """The run's log, created if needed; ``fresh`` discards a previous one."""
        path = directory / "runs" / run_name / "outcomes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if fresh and path.exists():
            path.unlink()
        return cls(path)

    def latest(self) -> dict[tuple[str, str], Outcome]:
        """Each question's last recorded outcome by (dataset, id), outages included."""
        records: dict[tuple[str, str], Outcome] = {}
        if not self.path.exists():
            return records
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                outcome = _decode(record["dataset"], record["outcome"])
                records[(record["dataset"], outcome.id)] = outcome
        return records

    def done(self) -> set[tuple[str, str]]:
        """Questions that need no new attempt (their latest outcome is not an outage)."""
        return {key for key, outcome in self.latest().items() if not outcome.infra_error}

    def append(self, dataset: Dataset, outcome: Outcome) -> None:
        """Record one finished question (flushed at once: a crash loses nothing)."""
        line = json.dumps(
            {"dataset": dataset, "outcome": jsonable_dict(outcome)}, ensure_ascii=False
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
