import json
from pathlib import Path

from tests.eval.support import attack, benign, gold, usage
from text2sql.eval import metrics as m
from text2sql.eval.report import base_name, failures, jsonable, write_reports
from text2sql.eval.report_markdown import render_comparison
from text2sql.eval.run_result import RunInfo, RunResult


def _result(
    *, smoke: bool = False, model: str = "openai/gpt-5.4", choice: str = "main"
) -> RunResult:
    golds = [gold("g1", correct=True), gold("g2", correct=False, difficulty="hard")]
    attacks = [attack("a1", "input_rules"), attack("a2", None, expected="input_classifier")]
    benigns = [benign("b1", "answered"), benign("b2", "blocked")]
    metrics = m.EvalMetrics(
        gold=m.gold_metrics(golds),
        attacks=m.attack_metrics(attacks),
        benign=m.benign_metrics(benigns),
        cost=m.cost_metrics([usage()] * 6),
    )
    info = RunInfo(
        date="2026-10-09",
        choice=choice,
        model=model,
        guard_model="openai/gpt-5.4-mini",
        prompts={"generate": "generate_v2", "input_guard": "input_guard_v2"},
        datasets={"gold": 2, "adversarial": 2, "benign_tricky": 2},
        cache=True,
        smoke=smoke,
        git_commit="abc1234",
        duration_s=12.0,
    )
    return RunResult(info, metrics, golds, attacks, benigns)


def test_file_names() -> None:
    assert base_name(_result().info) == "2026-10-09_openai-gpt-5.4"
    assert base_name(_result(smoke=True).info) == "2026-10-09_openai-gpt-5.4_smoke"
    assert (
        base_name(_result(model="ollama_chat/qwen2.5-coder:7b").info)
        == "2026-10-09_ollama-chat-qwen2.5-coder-7b"
    )


def test_jsonable_adds_rates() -> None:
    assert jsonable(m.Rate(4, 1)) == {"n": 4, "hits": 1, "rate": 0.25}


def test_failures_keep_the_sql() -> None:
    rows = failures(_result())
    assert [(r["kind"], r["id"]) for r in rows] == [
        ("gold", "g2"),
        ("attack_not_blocked", "a2"),
        ("false_block", "b2"),
    ]
    assert rows[0]["gold_sql"] == "SELECT 1"
    assert rows[0]["predicted_sql"] == "SELECT 2"


def test_write_reports(tmp_path: Path) -> None:
    paths = write_reports(_result(), tmp_path)
    assert [p.name for p in paths] == [
        "2026-10-09_openai-gpt-5.4.md",
        "2026-10-09_openai-gpt-5.4.json",
        "2026-10-09_openai-gpt-5.4_failures.jsonl",
    ]
    md = paths[0].read_text(encoding="utf-8")
    for heading in (
        "## Summary",
        "## Accuracy by difficulty",
        "## Accuracy by category",
        "## Attacks",
        "## False blocks",
        "## Failed gold questions (1)",
    ):
        assert heading in md
    assert "| Execution accuracy | 50.0% (1/2) |" in md
    data = json.loads(paths[1].read_text(encoding="utf-8"))
    assert data["metrics"]["gold"]["execution_accuracy"]["rate"] == 0.5
    assert len(paths[2].read_text(encoding="utf-8").splitlines()) == 3


def test_comparison_table() -> None:
    text = render_comparison([_result(), _result(model="ollama_chat/qwen", choice="local")])
    assert text.startswith("# Model comparison: main vs local")
    assert "| Execution accuracy | 50.0% (1/2) | 50.0% (1/2) |" in text
