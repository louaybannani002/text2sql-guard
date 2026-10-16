import dataclasses
from pathlib import Path

from tests.eval.support import attack, gold
from text2sql.eval.checkpoint import Checkpoint
from text2sql.eval.datasets import load_adversarial, load_gold
from text2sql.eval.run_result import RunInfo
from text2sql.eval.session import (
    PROVIDER_DOWN,
    Questions,
    RunOptions,
    collect,
    compute_metrics,
    default_run_name,
    questions,
)

OPTIONS = RunOptions(
    datasets=("gold", "adversarial", "benign"),
    smoke=False,
    concurrency=2,
    limit=None,
    use_cache=True,
    generate_prompt="generate_v2",
    guard_prompt="input_guard_v2",
    out_dir=Path("unused"),
)
INFO = RunInfo(
    date="2026-10-14",
    choice="main",
    model="gemini/gemini-3.8-flash",
    guard_model="gemini/gemini-3.5-flash-lite",
    prompts={},
    datasets={},
    cache=True,
    smoke=False,
    git_commit="abc",
    duration_s=1.0,
)


def test_run_names_are_stable_across_days_and_distinguish_prompts() -> None:
    name = default_run_name("gemini/gemini-3.8-flash", OPTIONS)
    assert name == "gemini-gemini-3.8-flash_generate_v2_input_guard_v2"
    v3 = dataclasses.replace(OPTIONS, generate_prompt="generate_v3", smoke=True, use_cache=False)
    assert default_run_name("gemini/gemini-3.8-flash", v3).endswith(
        "generate_v3_input_guard_v2_smoke_nocache"
    )
    pinned = dataclasses.replace(OPTIONS, fallbacks=False)
    assert default_run_name("m", pinned) == "m_generate_v2_input_guard_v2_nofallback"


def test_questions_honour_datasets_limit_and_smoke() -> None:
    q = questions(dataclasses.replace(OPTIONS, datasets=("gold",), limit=3))
    assert (len(q.gold), q.attacks, q.benign) == (3, [], [])
    smoke = questions(dataclasses.replace(OPTIONS, smoke=True))
    assert (len(smoke.gold), len(smoke.attacks), smoke.benign) == (15, 5, [])


def test_collect_reports_questions_not_run_yet(tmp_path: Path) -> None:
    pairs, attacks = load_gold()[:3], load_adversarial()[:1]
    checkpoint = Checkpoint.open(tmp_path, "run")
    checkpoint.append("gold", gold(pairs[0].id, correct=True))
    checkpoint.append("gold", gold(pairs[1].id, correct=False))
    checkpoint.append("adversarial", attack(attacks[0].id, "input_rules"))
    result = collect(checkpoint, Questions(pairs, attacks, []), INFO, tripped=True)
    assert result.metrics.gold is not None
    assert result.metrics.gold.execution_accuracy.n == 2
    assert result.metrics.notes == [
        PROVIDER_DOWN,
        "1 questions not run yet: run the same command again to resume",
    ]


def test_outages_are_left_out_of_the_rates() -> None:
    outage = dataclasses.replace(gold("g2", correct=False), infra_error=True)
    metrics = compute_metrics([gold("g1", correct=True), outage], [], [], notes=[])
    assert metrics.gold is not None
    assert metrics.gold.execution_accuracy.n == 1
    assert metrics.infrastructure_errors == ["g2"]
