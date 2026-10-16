import dataclasses
import json
from pathlib import Path

from tests.eval.support import attack, gold
from text2sql.eval.checkpoint import Checkpoint


def test_outcomes_survive_a_restart(tmp_path: Path) -> None:
    first = Checkpoint.open(tmp_path, "run-a")
    first.append("gold", gold("g1", correct=True))
    first.append("adversarial", attack("a1", "input_rules"))

    again = Checkpoint.open(tmp_path, "run-a")
    latest = again.latest()
    assert set(latest) == {("gold", "g1"), ("adversarial", "a1")}
    assert latest[("gold", "g1")] == gold("g1", correct=True)  # round trip, Usage included
    assert again.done() == {("gold", "g1"), ("adversarial", "a1")}
    assert first.path == tmp_path / "runs" / "run-a" / "outcomes.jsonl"


def test_outages_are_asked_again_and_the_latest_line_wins(tmp_path: Path) -> None:
    checkpoint = Checkpoint.open(tmp_path, "run-b")
    outage = gold("g1", correct=False, status="failed")
    checkpoint.append("gold", outage.__class__(**{**outage.__dict__, "infra_error": True}))
    assert checkpoint.done() == set()
    checkpoint.append("gold", gold("g1", correct=True))
    assert checkpoint.done() == {("gold", "g1")}
    assert checkpoint.latest()[("gold", "g1")].infra_error is False


def test_fresh_discards_the_previous_run(tmp_path: Path) -> None:
    Checkpoint.open(tmp_path, "run-c").append("gold", gold("g1", correct=True))
    assert Checkpoint.open(tmp_path, "run-c", fresh=True).latest() == {}


def test_models_round_trip_and_old_records_still_load(tmp_path: Path) -> None:
    checkpoint = Checkpoint.open(tmp_path, "run-a")
    with_models = gold("g1", correct=True)
    with_models = dataclasses.replace(
        with_models, usage=dataclasses.replace(with_models.usage, sql_models=("groq/x",))
    )
    checkpoint.append("gold", with_models)
    record = json.loads(checkpoint.path.read_text(encoding="utf-8"))
    record["outcome"]["id"] = "g0"
    del record["outcome"]["usage"]["sql_models"]  # written before the field existed
    with checkpoint.path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    latest = Checkpoint.open(tmp_path, "run-a").latest()
    assert latest[("gold", "g1")] == with_models
    assert latest[("gold", "g0")].usage.sql_models == ()
