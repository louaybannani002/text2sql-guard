"""Run the evaluation end to end and write reports (entry point: eval/run_eval.py).

Examples (from backend/):
    uv run python ../eval/run_eval.py                      # everything, main model
    uv run python ../eval/run_eval.py --smoke              # CI subset; exit 1 below thresholds
    uv run python ../eval/run_eval.py --model both         # main vs local (Ollama)
    uv run python ../eval/run_eval.py --prompt generate_v3 # another generation prompt

A run is resumable: the same command (same model and prompts, or the same --run-name) skips
the questions already answered and asks again the ones that hit a provider outage.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from text2sql.config.settings import Settings, get_settings
from text2sql.eval import metrics as m
from text2sql.eval.datasets import DATASETS_DIR
from text2sql.eval.pipeline_setup import ModelChoice, llm_for, local_model_reachable
from text2sql.eval.report import write_reports
from text2sql.eval.report_markdown import render_comparison, summary_rows
from text2sql.eval.run_result import RunInfo, RunResult
from text2sql.eval.session import PROVIDER_DOWN, RunOptions, evaluate
from text2sql.eval.smoke import load_smoke, threshold_failures
from text2sql.guard.input_guard import PROMPT_NAME as GUARD_PROMPT
from text2sql.observability.logging import configure_logging
from text2sql.pipeline.generate import PROMPT_NAME as GENERATE_PROMPT

DEFAULT_OUT = DATASETS_DIR.parent / "reports"
DATASETS = ("gold", "adversarial", "benign")


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


def _evaluated(result: RunResult) -> bool:
    metrics = result.metrics
    return any(x is not None for x in (metrics.gold, metrics.attacks, metrics.benign))


def options_from(args: argparse.Namespace) -> RunOptions:
    """Command-line arguments as run options."""
    return RunOptions(
        datasets=tuple(args.datasets),
        smoke=args.smoke,
        concurrency=args.concurrency,
        limit=args.limit,
        use_cache=not args.no_cache,
        generate_prompt=args.prompt,
        guard_prompt=args.guard_prompt,
        out_dir=args.out_dir,
        run_name=args.run_name,
        fresh=args.fresh,
        fallbacks=not args.no_fallback,
    )


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
        result = await evaluate(settings, choice, options_from(args))
        results.append(result)
        for path in write_reports(result, args.out_dir):
            print(f"[{choice}] wrote {path}")  # noqa: T201
        for name, value in summary_rows(result.metrics):
            print(f"[{choice}]   {name}: {value}")  # noqa: T201
        for note in result.metrics.notes:
            print(f"[{choice}] note: {note}", file=sys.stderr)  # noqa: T201
    if len(results) > 1:
        path = args.out_dir / f"{results[0].info.date}_main-vs-local.md"
        path.write_text(render_comparison(results), encoding="utf-8", newline="\n")
        print(f"wrote {path}")  # noqa: T201
    if any(PROVIDER_DOWN in r.metrics.notes for r in results):
        print(f"EVAL ABORTED: {PROVIDER_DOWN}", file=sys.stderr)  # noqa: T201
        return 3
    evaluated = [r for r in results if _evaluated(r)]
    if args.smoke:
        spec = load_smoke()
        problems = [p for r in evaluated for p in threshold_failures(r.metrics, spec)]
        for problem in problems or (["no model could be evaluated"] if not evaluated else []):
            print(f"SMOKE FAILED: {problem}", file=sys.stderr)  # noqa: T201
        return 1 if problems or not evaluated else 0
    return 0 if evaluated else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(prog="eval/run_eval.py", description=__doc__.split("\n")[0])
    parser.add_argument("--model", choices=["main", "local", "both"], default="main")
    parser.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    parser.add_argument("--smoke", action="store_true", help="20-question subset + thresholds")
    parser.add_argument("--prompt", default=GENERATE_PROMPT, help="generation prompt version")
    parser.add_argument("--guard-prompt", default=GUARD_PROMPT, help="input classifier prompt")
    parser.add_argument("--concurrency", type=int, default=2, help="questions in flight")
    parser.add_argument("--limit", type=int, default=None, help="first N per dataset")
    parser.add_argument("--no-cache", action="store_true", help="bypass the query cache")
    parser.add_argument(
        "--no-fallback", action="store_true", help="wait out rate limits, never switch model"
    )
    parser.add_argument("--run-name", default=None, help="resume key (default: model+prompts)")
    parser.add_argument("--fresh", action="store_true", help="discard the run's checkpoint")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run and return the exit code.

    0 ok, 1 smoke thresholds missed, 2 nothing could be evaluated, 3 the model provider kept
    failing (rate limit, exhausted quota, outage): run again later to resume.
    """
    configure_logging("WARNING", json=False)
    return asyncio.run(_main(parse_args(argv)))
