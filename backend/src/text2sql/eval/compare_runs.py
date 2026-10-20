"""Side-by-side comparison of evaluation runs, from their JSON reports.

Every number is recomputed from the per-question records, so all columns use the same
definitions. Latency is over gold questions only (blocked attacks answer in milliseconds and
would distort it). A column marked gold-only shows no attack or benign numbers, e.g. for a run
whose attack phase was hit by provider outages.
"""

import argparse
import json
import math
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from text2sql.eval.subset import load_subset_ids

INPUT_LAYERS = {"input_rules", "input_classifier"}
DIFFICULTIES = ("easy", "medium", "hard")


@dataclass(frozen=True)
class Column:
    """One report to compare, and whether only its gold results are trustworthy."""

    path: Path
    gold_only: bool = False


def _pct(hits: int, n: int) -> str:
    return f"{100 * hits / n:.1f}% ({hits}/{n})" if n else "-"


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


Record = dict[str, object]


def _records(report: Record, key: str) -> list[Record]:
    value = report.get(key, [])
    if not isinstance(value, list):
        msg = f"report field {key!r} is not a list"
        raise TypeError(msg)
    return [r for r in value if isinstance(r, dict)]


def _field(record: Record, *path: str) -> object:
    value: object = record
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _number(record: Record, *path: str) -> float:
    value = _field(record, *path)
    return float(value) if isinstance(value, int | float) else 0.0


def _sql_models(record: Record) -> list[str] | None:
    models = _field(record, "usage", "sql_models")
    return [str(m) for m in models] if isinstance(models, list) else None


def _fallback_rows(gold: list[Record], *, primary: str) -> dict[str, str]:
    """Which model wrote the SQL; unknown for reports written before it was recorded."""
    known = [(g, m) for g in gold if (m := _sql_models(g)) is not None]
    if not known:
        return {"Gold answers using a fallback model": "-", "Accuracy, primary model only": "-"}
    fallback = [g for g, models in known if any(m != primary for m in models)]
    primary_only = [g for g, models in known if models and all(m == primary for m in models)]
    return {
        "Gold answers using a fallback model": _pct(len(fallback), len(known)),
        "Accuracy, primary model only": _pct(
            sum(bool(g.get("correct")) for g in primary_only), len(primary_only)
        ),
    }


def _rows(report: Record, *, gold_only: bool, gold_ids: set[str] | None) -> dict[str, str]:
    info = _field(report, "info")
    info = info if isinstance(info, dict) else {}
    every = {key: _records(report, key) for key in ("gold", "attacks", "benign")}
    if gold_ids is not None:
        every["gold"] = [g for g in every["gold"] if g.get("id") in gold_ids]
    gold, attacks, benign = (
        [r for r in every[key] if not r.get("infra_error")] for key in ("gold", "attacks", "benign")
    )
    prompts = info.get("prompts")
    rows = {
        "Model (SQL / classifier)": f"`{info.get('model')}` / `{info.get('guard_model')}`",
        "Prompts": ", ".join(f"`{v}`" for v in prompts.values())
        if isinstance(prompts, dict) and prompts
        else "-",
        "Date, commit": f"{info.get('date')}, `{info.get('git_commit', '-')}`",
        "Execution accuracy": _pct(sum(bool(g.get("correct")) for g in gold), len(gold)),
    }
    for level in DIFFICULTIES:
        subset = [g for g in gold if g.get("difficulty") == level]
        rows[f"Accuracy: {level}"] = _pct(sum(bool(g.get("correct")) for g in subset), len(subset))
    rows.update(_fallback_rows(gold, primary=str(info.get("model"))))
    answered = [g for g in gold if g.get("status") == "answered"]
    rows["Valid SQL rate"] = _pct(len(answered), len(gold))
    blocked = [a for a in attacks if a.get("stopped_by") not in (None, "failed")]
    must_block = [a for a in attacks if a.get("expected_layer") in INPUT_LAYERS]
    false_blocks = [b for b in benign if b.get("status") in ("blocked", "rejected")]
    na = "n/a (provider outages during that run)"
    rows["Attack block rate (all)"] = na if gold_only else _pct(len(blocked), len(attacks))
    rows["Attack block rate (input-guard attacks)"] = (
        na if gold_only else _pct(sum(a in blocked for a in must_block), len(must_block))
    )
    rows["False-block rate (benign_tricky)"] = (
        na if gold_only else _pct(len(false_blocks), len(benign))
    )
    latencies = [_number(g, "usage", "total_ms") / 1000 for g in gold]
    p50, p95 = _percentile(latencies, 50), _percentile(latencies, 95)
    rows["Latency p50 / p95 (gold)"] = (
        f"{p50:.1f} s / {p95:.1f} s" if p50 is not None and p95 is not None else "-"
    )
    tokens = [_number(g, "usage", "tokens") for g in gold]
    rows["Avg tokens per gold question"] = f"{sum(tokens) / len(tokens):,.0f}" if tokens else "-"
    outages = [
        r for key in ("gold", "attacks", "benign") for r in every[key] if r.get("infra_error")
    ]
    rows["Provider outages (excluded)"] = str(len(outages))
    return rows


def _load(path: Path) -> Record:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        msg = f"{path.name} is not a run report"
        raise TypeError(msg)
    return report


def compare(
    columns: Sequence[Column], titles: Sequence[str], *, gold_ids: Collection[str] | None = None
) -> str:
    """Markdown table: one row per metric, one column per report.

    With ``gold_ids``, every column is scored on those gold questions only (e.g. a full run
    next to subset runs).
    """
    ids = set(gold_ids) if gold_ids is not None else None
    per_column = [_rows(_load(c.path), gold_only=c.gold_only, gold_ids=ids) for c in columns]
    metrics = list(dict.fromkeys(k for rows in per_column for k in rows))
    lines = ["| Metric | " + " | ".join(titles) + " |", "|---" * (len(titles) + 1) + "|"]
    lines += [
        f"| {metric} | " + " | ".join(rows.get(metric, "-") for rows in per_column) + " |"
        for metric in metrics
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Print (or write with --out) the comparison of the given run reports."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.eval.compare_runs")
    parser.add_argument(
        "--run", nargs=2, action="append", metavar=("TITLE", "REPORT_JSON"), required=True
    )
    parser.add_argument("--gold-only", action="append", default=[], metavar="TITLE")
    parser.add_argument(
        "--subset", action="store_true", help="score gold on compare_subset.json only"
    )
    parser.add_argument("--out", type=Path, default=None, help="write the table to this file")
    args = parser.parse_args(argv)
    titles = [title for title, _ in args.run]
    columns = [Column(Path(path), gold_only=title in args.gold_only) for title, path in args.run]
    table = compare(columns, titles, gold_ids=load_subset_ids() if args.subset else None)
    if args.out is None:
        sys.stdout.write(table)
    else:
        args.out.write_text(table, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
