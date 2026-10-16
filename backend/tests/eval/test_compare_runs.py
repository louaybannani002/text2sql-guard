import json
from pathlib import Path

import pytest

from text2sql.eval.compare_runs import Column, compare, main

INFO = {
    "date": "2026-10-14",
    "model": "gemini/x",
    "guard_model": "gemini/y",
    "prompts": {"generate": "generate_v2", "input_guard": "input_guard_v2"},
    "git_commit": "abc1234",
}


def _gold(i: int, *, difficulty: str, correct: bool, infra: bool = False) -> dict[str, object]:
    return {
        "id": f"g{i}",
        "difficulty": difficulty,
        "correct": correct,
        "status": "failed" if infra else "answered",
        "usage": {"total_ms": 1000.0 * (i + 1), "tokens": 100},
        "infra_error": infra,
    }


def _report(tmp_path: Path, name: str) -> Path:
    report = {
        "info": INFO,
        "gold": [
            _gold(0, difficulty="easy", correct=True),
            _gold(1, difficulty="medium", correct=False),
            _gold(2, difficulty="hard", correct=True),
            _gold(3, difficulty="hard", correct=False, infra=True),
        ],
        "attacks": [
            {"expected_layer": "input_rules", "stopped_by": "input_rules"},
            {"expected_layer": "sql_validator", "stopped_by": "failed"},
        ],
        "benign": [{"status": "blocked"}, {"status": "answered"}, {"status": "cannot_answer"}],
    }
    path = tmp_path / name
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _row(table: str, metric: str) -> list[str]:
    line = next(line for line in table.splitlines() if line.startswith(f"| {metric} |"))
    return [cell.strip() for cell in line.strip("|").split("|")][1:]


def test_recomputes_metrics_and_excludes_outages(tmp_path: Path) -> None:
    table = compare([Column(_report(tmp_path, "a.json"))], ["A"])
    assert _row(table, "Execution accuracy") == ["66.7% (2/3)"]
    assert _row(table, "Accuracy: hard") == ["100.0% (1/1)"]
    assert _row(table, "Attack block rate (all)") == ["50.0% (1/2)"]
    assert _row(table, "Attack block rate (input-guard attacks)") == ["100.0% (1/1)"]
    assert _row(table, "False-block rate (benign_tricky)") == ["33.3% (1/3)"]
    assert _row(table, "Latency p50 / p95 (gold)") == ["2.0 s / 3.0 s"]
    assert _row(table, "Provider outages (excluded)") == ["1"]


def test_gold_only_column_hides_guardrail_numbers(tmp_path: Path) -> None:
    path = _report(tmp_path, "a.json")
    table = compare([Column(path), Column(path, gold_only=True)], ["A", "B"])
    attack = _row(table, "Attack block rate (all)")
    assert attack[0] == "50.0% (1/2)"
    assert attack[1].startswith("n/a")
    assert _row(table, "Execution accuracy") == ["66.7% (2/3)", "66.7% (2/3)"]


def test_rejects_a_file_that_is_not_a_report(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="not a run report"):
        compare([Column(path)], ["X"])


def test_main_writes_the_table(tmp_path: Path) -> None:
    path = _report(tmp_path, "a.json")
    out = tmp_path / "cmp.md"
    assert (
        main(
            [
                "--run",
                "A",
                str(path),
                "--run",
                "B",
                str(path),
                "--gold-only",
                "B",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert text.startswith("| Metric | A | B |")
    assert "n/a" in text


def test_splits_answers_by_the_model_that_wrote_the_sql(tmp_path: Path) -> None:
    gold = [
        {**_gold(0, difficulty="easy", correct=True), "usage": {"sql_models": ["gemini/x"]}},
        {**_gold(1, difficulty="easy", correct=False), "usage": {"sql_models": ["gemini/x"]}},
        {**_gold(2, difficulty="easy", correct=True), "usage": {"sql_models": ["groq/y"]}},
        {**_gold(3, difficulty="easy", correct=True), "usage": {"sql_models": []}},  # blocked
    ]
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"info": INFO, "gold": gold}), encoding="utf-8")
    table = compare([Column(path), Column(_report(tmp_path, "old.json"))], ["new", "old"])
    assert _row(table, "Gold answers using a fallback model") == ["25.0% (1/4)", "-"]
    assert _row(table, "Accuracy, primary model only") == ["50.0% (1/2)", "-"]
