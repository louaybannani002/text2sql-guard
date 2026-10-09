"""Markdown rendering of an evaluation run, and of a side-by-side model comparison."""

from collections.abc import Sequence

from text2sql.eval.metrics import EvalMetrics, Rate
from text2sql.eval.run_result import RunResult

LAYERS = (
    "input_rules",
    "input_classifier",
    "generator",
    "sql_validator",
    "executor",
    "database",
    "answered_safely",
    "failed",
)


def pct(rate: Rate | None) -> str:
    """``87.3% (131/150)``, or ``-`` when there is nothing to rate."""
    if rate is None or rate.rate is None:
        return "-"
    return f"{rate.rate:.1%} ({rate.hits}/{rate.n})"


def _num(value: float | None, unit: str = "", digits: int = 0) -> str:
    return "-" if value is None else f"{value:,.{digits}f}{unit}"


def summary_rows(m: EvalMetrics) -> list[tuple[str, str]]:
    """(metric, value) pairs shared by the report and the comparison."""
    rows: list[tuple[str, str]] = [
        ("Infrastructure errors (excluded)", str(len(m.infrastructure_errors)))
    ]
    if m.gold:
        rows += [
            ("Execution accuracy", pct(m.gold.execution_accuracy)),
            ("Valid SQL rate", pct(m.gold.valid_sql)),
            ("Answerable precision", pct(m.gold.answerable_precision)),
            ("Said cannot answer", str(m.gold.cannot_answer)),
        ]
    if m.attacks:
        rows += [
            ("Attack block rate (all)", pct(m.attacks.blocked)),
            ("Attack block rate (input-guard attacks)", pct(m.attacks.input_guard_blocked)),
            ("Stopped at the expected layer", pct(m.attacks.at_expected_layer)),
        ]
    if m.benign:
        rows += [("False-block rate (benign_tricky)", pct(m.benign.false_blocked))]
    if m.cost:
        c = m.cost
        rows += [
            (
                "Latency p50 / p95",
                f"{_num(c.latency_p50_ms, ' ms')} / {_num(c.latency_p95_ms, ' ms')}",
            ),
            ("Avg tokens per question", _num(c.avg_tokens)),
            ("Avg cost per question", _num(c.avg_cost_usd, " USD", 5)),
            ("Cache hit rate", pct(c.cache_hits)),
        ]
    return rows


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def render(result: RunResult, *, failures_file: str) -> str:
    """The full report for one run."""
    info, m = result.info, result.metrics
    out = [
        f"# Evaluation: {info.model}{' (smoke)' if info.smoke else ''}",
        "",
        f"- Date: {info.date}, commit `{info.git_commit}`, {info.duration_s:.0f} s",
        f"- SQL model (`main` role): `{info.model}`; input classifier: `{info.guard_model}`",
        f"- Prompts: {', '.join(f'`{v}`' for v in info.prompts.values())}",
        (
            f"- Questions: {', '.join(f'{k} {v}' for k, v in info.datasets.items())}; "
            f"cache {'on' if info.cache else 'off'}"
        ),
        *[f"- Note: {note}" for note in m.notes],
        "",
        "## Summary",
        "",
        *_table(["Metric", "Value"], summary_rows(m)),
    ]
    if m.gold:
        out += ["", "## Accuracy by difficulty", ""]
        out += _table(
            ["Difficulty", "Accuracy"], [(k, pct(v)) for k, v in m.gold.by_difficulty.items()]
        )
        out += ["", "## Accuracy by category", ""]
        out += _table(
            ["Category", "Accuracy"], [(k, pct(v)) for k, v in m.gold.by_category.items()]
        )
    if m.attacks:
        out += ["", "## Attacks: block rate and the layer that stopped them", ""]
        layers = [
            layer
            for layer in LAYERS
            if any(layer in v for v in m.attacks.layers_by_category.values())
        ]
        rows = [
            [cat, pct(m.attacks.by_category[cat]), *[str(counts.get(layer, 0)) for layer in layers]]
            for cat, counts in m.attacks.layers_by_category.items()
        ]
        out += _table(["Category", "Blocked", *layers], rows)
        out += [
            "",
            (
                "`answered_safely`: the pipeline answered with validated, read-only SQL (no harm, "
                "but not a block). `failed`: a pipeline error, not counted as a block."
            ),
        ]
    if m.benign:
        unexpected = ", ".join(m.benign.unexpected_false_blocks) or "none"
        layers_text = ", ".join(f"{k}: {v}" for k, v in m.benign.layers.items()) or "none"
        out += [
            "",
            "## False blocks",
            "",
            f"- Rate: {pct(m.benign.false_blocked)}",
            f"- By layer: {layers_text}",
        ]
        out += [f"- Not yet recorded as known false blocks: {unexpected}"]
    wrong = [o for o in result.gold if not o.correct]
    if wrong:
        out += [
            "",
            f"## Failed gold questions ({len(wrong)})",
            "",
            f"Details with SQL: `{failures_file}`.",
            "",
        ]
        out += _table(["id", "status", "reason"], [(o.id, o.status, o.reason) for o in wrong])
    return "\n".join(out) + "\n"


def render_comparison(results: Sequence[RunResult]) -> str:
    """Side-by-side summary of runs with different models."""
    header = ["Metric", *[f"{r.info.choice}: `{r.info.model}`" for r in results]]
    per_run = [dict(summary_rows(r.metrics)) for r in results]
    metrics = list(dict.fromkeys(k for rows in per_run for k in rows))
    rows = [[metric, *[run.get(metric, "-") for run in per_run]] for metric in metrics]
    title = " vs ".join(r.info.choice for r in results)
    return "\n".join([f"# Model comparison: {title}", "", *_table(header, rows)]) + "\n"
