"""One evaluation run: select questions, resume from the checkpoint, run, compute metrics."""

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from text2sql.config.settings import Settings
from text2sql.eval import metrics as m
from text2sql.eval.checkpoint import Checkpoint, Dataset
from text2sql.eval.datasets import (
    Attack,
    BenignCase,
    GoldPair,
    load_adversarial,
    load_benign_tricky,
    load_gold,
)
from text2sql.eval.outcomes import AttackOutcome, BenignOutcome, GoldOutcome, Outcome
from text2sql.eval.pipeline_setup import ModelChoice, llm_for, open_pipeline
from text2sql.eval.run_result import RunInfo, RunResult
from text2sql.eval.runner import CircuitBreaker, pipeline_answer, run_attacks, run_benign, run_gold
from text2sql.eval.smoke import load_smoke, select
from text2sql.eval.subset import load_subset_ids

PROVIDER_DOWN = (
    "aborted: the model provider failed for several questions in a row (rate limit, exhausted "
    "quota or outage); the remaining questions were not run. Run the same command again later "
    "to resume."
)


@dataclass(frozen=True)
class RunOptions:
    """What to evaluate and how (the command-line options)."""

    datasets: tuple[str, ...]
    smoke: bool
    concurrency: int
    limit: int | None
    use_cache: bool
    generate_prompt: str
    guard_prompt: str
    out_dir: Path
    run_name: str | None = None  # default: model + prompts (+ smoke / nocache)
    fresh: bool = False  # discard the run's checkpoint
    fallbacks: bool = True  # False: wait for a rate-limited model instead of replacing it
    subset: bool = (
        False  # gold: only the fixed comparison subset (eval/datasets/compare_subset.json)
    )


@dataclass(frozen=True)
class Questions:
    """The questions of one run."""

    gold: list[GoldPair]
    attacks: list[Attack]
    benign: list[BenignCase]


def default_run_name(model: str, options: RunOptions) -> str:
    """Stable across days, so a run limited by free-tier quotas can be resumed."""
    parts = [re.sub(r"[^A-Za-z0-9.]+", "-", model).strip("-"), options.generate_prompt]
    parts += [options.guard_prompt, *(["smoke"] if options.smoke else [])]
    parts += ["subset"] if options.subset else []
    parts += [] if options.use_cache else ["nocache"]
    return "_".join(parts + ([] if options.fallbacks else ["nofallback"]))


async def git_commit() -> str:
    """Short commit hash, or "unknown"."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *("git", "rev-parse", "--short", "HEAD"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return "unknown"
    return out.decode().strip() or "unknown"


def questions(options: RunOptions) -> Questions:
    """The datasets (or the smoke subset), limited as requested."""
    gold, attacks, benign = load_gold(), load_adversarial(), load_benign_tricky()
    if options.smoke:
        spec = load_smoke()
        gold, attacks, benign = select(gold, spec.gold_ids), select(attacks, spec.attack_ids), []
    elif options.subset:
        gold = select(gold, load_subset_ids())
    return Questions(
        gold=gold[: options.limit] if "gold" in options.datasets else [],
        attacks=attacks[: options.limit] if "adversarial" in options.datasets else [],
        benign=benign[: options.limit] if "benign" in options.datasets else [],
    )


def compute_metrics(
    gold: Sequence[GoldOutcome],
    attacks: Sequence[AttackOutcome],
    benign: Sequence[BenignOutcome],
    *,
    notes: list[str],
) -> m.EvalMetrics:
    """Metrics over the outcomes; outages are reported apart and left out of every rate."""
    every: list[Outcome] = [*gold, *attacks, *benign]
    gold_ok = [o for o in gold if not o.infra_error]
    attacks_ok = [o for o in attacks if not o.infra_error]
    benign_ok = [o for o in benign if not o.infra_error]
    kept: list[Outcome] = [*gold_ok, *attacks_ok, *benign_ok]
    return m.EvalMetrics(
        gold=m.gold_metrics(gold_ok) if gold_ok else None,
        attacks=m.attack_metrics(attacks_ok) if attacks_ok else None,
        benign=m.benign_metrics(benign_ok) if benign_ok else None,
        cost=m.cost_metrics([o.usage for o in kept]),
        infrastructure_errors=[o.id for o in every if o.infra_error],
        notes=notes,
    )


async def evaluate(settings: Settings, choice: ModelChoice, options: RunOptions) -> RunResult:
    """Run (or resume) one evaluation and compute its metrics."""
    started = time.perf_counter()
    model = llm_for(settings, choice).models["main"]
    run_name = options.run_name or default_run_name(model, options)
    checkpoint = Checkpoint.open(options.out_dir, run_name, fresh=options.fresh)
    done = checkpoint.done()
    q = questions(options)
    pipeline = await open_pipeline(
        settings,
        choice,
        use_cache=options.use_cache,
        generate_prompt=options.generate_prompt,
        guard_prompt=options.guard_prompt,
        fallbacks=options.fallbacks,
    )
    breaker = CircuitBreaker()
    try:
        answer = pipeline_answer(pipeline, breaker=breaker)
        n = options.concurrency

        gold = [g for g in q.gold if ("gold", g.id) not in done]
        await run_gold(pipeline, answer, gold, n, _Saver(checkpoint, "gold"))
        attacks = [a for a in q.attacks if ("adversarial", a.id) not in done]
        await run_attacks(answer, attacks, n, _Saver(checkpoint, "adversarial"))
        benign = [b for b in q.benign if ("benign", b.id) not in done]
        await run_benign(answer, benign, n, _Saver(checkpoint, "benign"))
    finally:
        await pipeline.close()
    info = RunInfo(
        date=datetime.now(UTC).date().isoformat(),
        choice=choice,
        model=pipeline.model,
        guard_model=pipeline.guard_model,
        prompts={"generate": options.generate_prompt, "input_guard": options.guard_prompt},
        datasets={
            "gold": len(q.gold),
            "adversarial": len(q.attacks),
            "benign_tricky": len(q.benign),
        },
        cache=options.use_cache,
        smoke=options.smoke,
        git_commit=await git_commit(),
        duration_s=round(time.perf_counter() - started, 1),
        run_name=run_name,
        resumed=len(done),
    )
    return collect(checkpoint, q, info, tripped=breaker.tripped)


class _Saver:
    """``on_outcome`` callback that appends to the checkpoint."""

    def __init__(self, checkpoint: Checkpoint, dataset: Dataset) -> None:
        self.checkpoint = checkpoint
        self.dataset: Dataset = dataset

    def __call__(self, outcome: Outcome) -> None:
        self.checkpoint.append(self.dataset, outcome)


def collect(checkpoint: Checkpoint, q: Questions, info: RunInfo, *, tripped: bool) -> RunResult:
    """The run's result from every recorded outcome (this invocation's and earlier ones)."""
    latest = checkpoint.latest()
    gold = [o for g in q.gold if isinstance(o := latest.get(("gold", g.id)), GoldOutcome)]
    attacks = [
        o for a in q.attacks if isinstance(o := latest.get(("adversarial", a.id)), AttackOutcome)
    ]
    benign = [o for b in q.benign if isinstance(o := latest.get(("benign", b.id)), BenignOutcome)]
    missing = len(q.gold) + len(q.attacks) + len(q.benign) - len(gold) - len(attacks) - len(benign)
    notes = [PROVIDER_DOWN] if tripped else []
    if missing:
        notes.append(f"{missing} questions not run yet: run the same command again to resume")
    metrics = compute_metrics(gold, attacks, benign, notes=notes)
    return RunResult(info, metrics, gold, attacks, benign)
