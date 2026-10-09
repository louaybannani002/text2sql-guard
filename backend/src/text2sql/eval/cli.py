"""Run the evaluation end to end and write reports (entry point: eval/run_eval.py).

Examples (from backend/):
    uv run python ../eval/run_eval.py                      # everything, main model
    uv run python ../eval/run_eval.py --smoke              # CI subset; exit 1 below thresholds
    uv run python ../eval/run_eval.py --model both         # main vs local (Ollama)
"""

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from text2sql.config.settings import Settings, get_settings
from text2sql.eval import metrics as m
from text2sql.eval.datasets import DATASETS_DIR, load_adversarial, load_benign_tricky, load_gold
from text2sql.eval.pipeline_setup import ModelChoice, llm_for, local_model_reachable, open_pipeline
from text2sql.eval.report import write_reports
from text2sql.eval.report_markdown import render_comparison, summary_rows
from text2sql.eval.run_result import RunInfo, RunResult
from text2sql.eval.runner import (
    CircuitBreaker,
    pipeline_answer,
    run_attacks,
    run_benign,
    run_gold,
)
from text2sql.eval.smoke import load_smoke, select, threshold_failures
from text2sql.guard.input_guard import PROMPT_NAME as GUARD_PROMPT
from text2sql.observability.logging import configure_logging
from text2sql.pipeline.generate import PROMPT_NAME as GENERATE_PROMPT

if TYPE_CHECKING:
    from text2sql.eval.outcomes import Outcome

DEFAULT_OUT = DATASETS_DIR.parent / "reports"
DATASETS = ("gold", "adversarial", "benign")
PROVIDER_DOWN = (
    "aborted: the model provider failed for several questions in a row (rate limit, exhausted "
    "quota or outage); the remaining questions were not run. Check the API key's quota."
)


async def _git_commit() -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--short",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return "unknown"
    return out.decode().strip() or "unknown"


async def evaluate(  # noqa: PLR0913 - the CLI's options, passed explicitly
    settings: Settings,
    choice: ModelChoice,
    *,
    datasets: tuple[str, ...],
    smoke: bool,
    concurrency: int,
    limit: int | None,
    use_cache: bool,
) -> RunResult:
    """One run of the pipeline over the selected datasets."""
    started = time.perf_counter()
    gold, attacks, benign = load_gold(), load_adversarial(), load_benign_tricky()
    if smoke:
        spec = load_smoke()
        gold, attacks, benign = select(gold, spec.gold_ids), select(attacks, spec.attack_ids), []
    gold = gold[:limit] if "gold" in datasets else []
    attacks = attacks[:limit] if "adversarial" in datasets else []
    benign = benign[:limit] if "benign" in datasets else []

    pipeline = await open_pipeline(settings, choice, use_cache=use_cache)
    try:
        breaker = CircuitBreaker()
        answer = pipeline_answer(pipeline, breaker=breaker)
        gold_out = await run_gold(pipeline, answer, gold, concurrency)
        attack_out = await run_attacks(answer, attacks, concurrency)
        benign_out = await run_benign(answer, benign, concurrency)
    finally:
        await pipeline.close()

    every: list[Outcome] = [*gold_out, *attack_out, *benign_out]
    infra = [o.id for o in every if o.infra_error]
    gold_ok = [o for o in gold_out if not o.infra_error]
    attacks_ok = [o for o in attack_out if not o.infra_error]
    benign_ok = [o for o in benign_out if not o.infra_error]
    kept: list[Outcome] = [*gold_ok, *attacks_ok, *benign_ok]
    usages = [o.usage for o in kept]
    metrics = m.EvalMetrics(
        gold=m.gold_metrics(gold_ok) if gold_ok else None,
        attacks=m.attack_metrics(attacks_ok) if attacks_ok else None,
        benign=m.benign_metrics(benign_ok) if benign_ok else None,
        cost=m.cost_metrics(usages),
        infrastructure_errors=infra,
        notes=[PROVIDER_DOWN] if breaker.tripped else [],
    )
    info = RunInfo(
        date=datetime.now(UTC).date().isoformat(),
        choice=choice,
        model=pipeline.model,
        guard_model=pipeline.guard_model,
        prompts={"generate": GENERATE_PROMPT, "input_guard": GUARD_PROMPT},
        datasets={"gold": len(gold), "adversarial": len(attacks), "benign_tricky": len(benign)},
        cache=use_cache,
        smoke=smoke,
        git_commit=await _git_commit(),
        duration_s=round(time.perf_counter() - started, 1),
    )
    return RunResult(info, metrics, gold_out, attack_out, benign_out)


def skipped(settings: Settings, choice: ModelChoice, reason: str, *, smoke: bool) -> RunResult:
    """A placeholder result for a model that could not be evaluated."""
    llm = llm_for(settings, choice)
    info = RunInfo(
        date=datetime.now(UTC).date().isoformat(),
        choice=choice,
        model=llm.models["main"],
        guard_model=llm.models["fast"],
        prompts={},
        datasets={},
        cache=False,
        smoke=smoke,
        git_commit="-",
        duration_s=0.0,
    )
    return RunResult(info, m.EvalMetrics(notes=[f"skipped: {reason}"]))


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    choices: list[ModelChoice] = ["main", "local"] if args.model == "both" else [args.model]
    results: list[RunResult] = []
    for choice in choices:
        if choice == "local" and not await local_model_reachable(settings.llm_local_api_base):
            reason = f"local model server not reachable at {settings.llm_local_api_base}"
            print(f"[{choice}] {reason}", file=sys.stderr)  # noqa: T201
            results.append(skipped(settings, choice, reason, smoke=args.smoke))
            continue
        result = await evaluate(
            settings,
            choice,
            datasets=tuple(args.datasets),
            smoke=args.smoke,
            concurrency=args.concurrency,
            limit=args.limit,
            use_cache=not args.no_cache,
        )
        results.append(result)
        for path in write_reports(result, args.out_dir):
            print(f"[{choice}] wrote {path}")  # noqa: T201
        for name, value in summary_rows(result.metrics):
            print(f"[{choice}]   {name}: {value}")  # noqa: T201
    if len(results) > 1:
        path = args.out_dir / f"{results[0].info.date}_main-vs-local.md"
        path.write_text(render_comparison(results), encoding="utf-8", newline="\n")
        print(f"wrote {path}")  # noqa: T201
    if any(PROVIDER_DOWN in r.metrics.notes for r in results):
        print(f"EVAL ABORTED: {PROVIDER_DOWN}", file=sys.stderr)  # noqa: T201
        return 3
    if args.smoke:
        spec = load_smoke()
        evaluated = [r for r in results if not r.metrics.notes]
        problems = [p for r in evaluated for p in threshold_failures(r.metrics, spec)]
        for problem in problems or (["no model could be evaluated"] if not evaluated else []):
            print(f"SMOKE FAILED: {problem}", file=sys.stderr)  # noqa: T201
        return 1 if problems or not evaluated else 0
    return 0 if any(not r.metrics.notes for r in results) else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(prog="eval/run_eval.py", description=__doc__.split("\n")[0])
    parser.add_argument("--model", choices=["main", "local", "both"], default="main")
    parser.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    parser.add_argument("--smoke", action="store_true", help="20-question subset + thresholds")
    parser.add_argument("--concurrency", type=int, default=2, help="questions in flight")
    parser.add_argument("--limit", type=int, default=None, help="first N per dataset")
    parser.add_argument("--no-cache", action="store_true", help="bypass the query cache")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run and return the exit code.

    0 ok, 1 smoke thresholds missed, 2 nothing could be evaluated, 3 the model provider kept
    failing (rate limit, exhausted quota, outage) and the run was aborted.
    """
    configure_logging("WARNING", json=False)
    return asyncio.run(_main(parse_args(argv)))
