"""The evaluation datasets are well-formed and their labels match the real guards (offline).

Execution of the gold SQL and of executor/database payloads: tests/integration/
test_eval_datasets.py. Classifier labels against the real model: test_datasets_live.py.
"""

import json
import tomllib
from collections import Counter
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from text2sql.eval.datasets import (
    LAYER_ORDER,
    Attack,
    BenignCase,
    GoldPair,
    load_adversarial,
    load_benign_tricky,
    load_gold,
    needs_review,
)
from text2sql.guard.input_rules import check_rules
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_validator import Rejection, validate

BACKEND = Path(__file__).parents[2]
GOLD = load_gold()
ATTACKS = load_adversarial()
BENIGN = load_benign_tricky()


@pytest.fixture(scope="module")
def policy() -> SqlPolicy:
    fixture = json.loads((BACKEND / "tests/guard/fixtures/shop_policy.json").read_text())
    return SqlPolicy(
        readable_columns={k: frozenset(v) for k, v in fixture["readable_columns"].items()},
        personal_columns={k: frozenset(v) for k, v in fixture["personal_columns"].items()},
    )


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip("?.!")


# ---------------------------------------------------------------- shape


def test_sizes_and_unique_ids() -> None:
    assert (len(GOLD), len(ATTACKS), len(BENIGN)) == (150, 60, 30)
    for records in (GOLD, ATTACKS, BENIGN):
        ids = [r.id for r in records]
        assert len(ids) == len(set(ids))
        questions = [_norm(r.question) for r in records]
        assert len(questions) == len(set(questions))


def test_gold_is_balanced() -> None:
    assert Counter(p.category for p in GOLD) == dict.fromkeys(
        ("sales", "delivery", "reviews", "sellers", "products"), 30
    )
    assert Counter(p.difficulty for p in GOLD) == {"easy": 45, "medium": 60, "hard": 45}


def test_attacks_cover_every_category() -> None:
    assert Counter(a.category for a in ATTACKS) == dict.fromkeys(
        (
            "destructive_sql",
            "prompt_injection",
            "personal_data",
            "resource_exhaustion",
            "obfuscated",
        ),
        12,
    )


def test_gold_does_not_repeat_the_few_shot_examples() -> None:
    examples = tomllib.loads((BACKEND / "db/seeds/examples.toml").read_text(encoding="utf-8"))
    few_shot = {_norm(e["question"]) for e in examples["example"]}
    assert not few_shot & {_norm(p.question) for p in GOLD}  # else the eval measures recall


def test_ambiguous_pairs_are_listed() -> None:
    flagged = needs_review(GOLD)
    assert flagged
    assert all(len(p.review or "") > 20 for p in flagged)


# ---------------------------------------------------------------- gold SQL


@pytest.mark.parametrize("pair", GOLD, ids=lambda p: p.id)
def test_gold_sql_passes_the_validator(pair: GoldPair, policy: SqlPolicy) -> None:
    result = validate(pair.sql, policy)
    assert not isinstance(result, Rejection), f"{result.rule}: {result.reason}"
    assert sorted(result.tables) == pair.tables


@pytest.mark.parametrize("pair", GOLD, ids=lambda p: p.id)
def test_difficulty_matches_the_sql(pair: GoldPair) -> None:
    tree = sqlglot.parse_one(pair.sql, read="postgres")
    window = tree.find(exp.Window) is not None
    cte = tree.find(exp.CTE) is not None
    aggregate = tree.find(exp.AggFunc) is not None
    if pair.difficulty == "easy":
        assert len(pair.tables) == 1
    elif pair.difficulty == "medium":
        assert len(pair.tables) >= 2
        assert aggregate
        assert not window
        assert not cte
    else:
        assert window or cte


# ---------------------------------------------------------------- attacks


@pytest.mark.parametrize("attack", ATTACKS, ids=lambda a: a.id)
def test_attack_first_layer_matches_the_rules(attack: Attack) -> None:
    hit = check_rules(attack.question)
    if attack.expected_layer == "input_rules":
        assert hit is not None, "layer 1 should block this"
    else:
        assert hit is None, f"layer 1 already blocks it: {hit}"


@pytest.mark.parametrize("attack", [a for a in ATTACKS if a.sql], ids=lambda a: a.id)
def test_attack_sql_against_the_validator(attack: Attack, policy: SqlPolicy) -> None:
    assert attack.sql is not None
    result = validate(attack.sql, policy)
    if "sql_validator" in attack.sql_blocked_by:
        assert isinstance(result, Rejection), "the validator accepted the payload"
        assert result.rule == attack.validator_rule
    else:
        assert not isinstance(result, Rejection), "a later layer is meant to stop this one"


def test_defense_in_depth_layers_come_after_the_first() -> None:
    for attack in ATTACKS:
        first = LAYER_ORDER.index(attack.expected_layer)
        assert all(LAYER_ORDER.index(layer) >= first for layer in attack.sql_blocked_by), attack.id


# ---------------------------------------------------------------- benign tricky


@pytest.mark.parametrize("case", BENIGN, ids=lambda b: b.id)
def test_benign_questions_pass_layer_1(case: BenignCase) -> None:
    hit = check_rules(case.question)
    known = case.known_false_block or ""
    if known.startswith("input_rules:"):
        assert hit is not None
        assert known == f"input_rules:{hit.rule}"
    else:
        assert hit is None, f"false block: {hit}"
