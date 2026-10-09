"""Write evaluation reports: Markdown for people, JSON for tools, JSONL of failed cases."""

import dataclasses
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from text2sql.eval.metrics import Rate
from text2sql.eval.report_markdown import render
from text2sql.eval.run_result import RunInfo, RunResult

if TYPE_CHECKING:
    from text2sql.eval.outcomes import Outcome


def jsonable(value: object) -> object:
    """Dataclasses → dicts (with each Rate's computed ``rate``), recursively."""
    if isinstance(value, Rate):
        return {"n": value.n, "hits": value.hits, "rate": value.rate}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


def base_name(info: RunInfo) -> str:
    """``<date>_<model>[_smoke]``, safe as a file name."""
    model = re.sub(r"[^A-Za-z0-9.]+", "-", info.model).strip("-")
    return f"{info.date}_{model}{'_smoke' if info.smoke else ''}"


def failures(result: RunResult) -> list[dict[str, object]]:
    """Cases to study: outages, wrong gold answers, missed input-guard attacks, false blocks."""
    every: list[Outcome] = [*result.gold, *result.attacks, *result.benign]
    rows: list[dict[str, object]] = [
        {"kind": "infrastructure_error", **jsonable_dict(o)} for o in every if o.infra_error
    ]
    rows += [
        {"kind": "gold", **jsonable_dict(o)}
        for o in result.gold
        if not o.correct and not o.infra_error
    ]
    rows += [
        {"kind": "attack_not_blocked", **jsonable_dict(o)}
        for o in result.attacks
        if not o.blocked
        and not o.infra_error
        and o.expected_layer in {"input_rules", "input_classifier"}
    ]
    rows += [
        {"kind": "false_block", **jsonable_dict(o)}
        for o in result.benign
        if o.false_block and not o.infra_error
    ]
    return rows


def jsonable_dict(value: object) -> dict[str, object]:
    """``jsonable`` for a dataclass instance."""
    converted = jsonable(value)
    return converted if isinstance(converted, dict) else {"value": converted}


def write_reports(result: RunResult, directory: Path) -> list[Path]:
    """Write the .md, .json and _failures.jsonl files; returns their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    name = base_name(result.info)
    md = directory / f"{name}.md"
    js = directory / f"{name}.json"
    fails = directory / f"{name}_failures.jsonl"
    md.write_text(render(result, failures_file=fails.name), encoding="utf-8", newline="\n")
    payload = {
        "info": jsonable(result.info),
        "metrics": jsonable(result.metrics),
        "gold": jsonable(list(result.gold)),
        "attacks": jsonable(list(result.attacks)),
        "benign": jsonable(list(result.benign)),
    }
    js.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    lines = [json.dumps(row, ensure_ascii=False) for row in failures(result)]
    fails.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")
    return [md, js, fails]
