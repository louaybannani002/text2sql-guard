from tests.eval.support import attack, benign, gold, usage
from text2sql.eval.metrics import (
    Rate,
    attack_metrics,
    benign_metrics,
    cost_metrics,
    gold_metrics,
    percentile,
)


def test_rate() -> None:
    assert Rate(4, 3).rate == 0.75
    assert Rate(0, 0).rate is None


def test_percentile_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert (percentile(values, 50), percentile(values, 95)) == (50.0, 95.0)
    assert percentile([], 50) is None


def test_gold_metrics() -> None:
    outcomes = [
        gold("a", correct=True, difficulty="easy", category="sales"),
        gold("b", correct=False, difficulty="hard", category="sales"),
        gold("c", correct=False, difficulty="hard", category="reviews", status="failed"),
        gold("d", correct=False, difficulty="easy", category="reviews", status="cannot_answer"),
    ]
    m = gold_metrics(outcomes)
    assert m.execution_accuracy == Rate(4, 1)
    assert m.valid_sql == Rate(4, 2)
    assert m.answerable_precision == Rate(2, 1)
    assert m.cannot_answer == 1
    assert m.by_difficulty == {"easy": Rate(2, 1), "hard": Rate(2, 0)}
    assert m.by_category == {"reviews": Rate(2, 0), "sales": Rate(2, 1)}


def test_attack_metrics() -> None:
    outcomes = [
        attack("1", "input_rules"),
        attack("2", "input_classifier", expected="input_rules"),
        attack("3", None, category="personal_data", expected="generator"),
        attack("4", "executor", category="resource_exhaustion", expected="executor"),
        attack("5", "failed", category="resource_exhaustion", expected="input_classifier"),
    ]
    m = attack_metrics(outcomes)
    assert m.blocked == Rate(5, 3)
    assert m.input_guard_blocked == Rate(3, 2)  # attacks 1, 2 and 5 are the input guard's job
    assert m.at_expected_layer == Rate(5, 2)
    assert m.by_category["destructive_sql"] == Rate(2, 2)
    assert m.layers_by_category["resource_exhaustion"] == {"executor": 1, "failed": 1}
    assert (m.answered_safely, m.failed) == (1, 1)


def test_benign_metrics() -> None:
    m = benign_metrics(
        [
            benign("1", "answered"),
            benign("2", "blocked"),
            benign("3", "blocked", known="input_rules:x"),
        ]
    )
    assert m.false_blocked == Rate(3, 2)
    assert m.unexpected_false_blocks == ["2"]
    assert m.layers == {"input_classifier": 2}


def test_cost_metrics() -> None:
    m = cost_metrics([usage(100, 10, 0.01, "exact"), usage(300, 30, None), usage(200, 20, 0.03)])
    assert (m.latency_p50_ms, m.latency_p95_ms) == (200, 300)
    assert m.avg_tokens == 20
    assert m.avg_cost_usd == 0.02
    assert m.cost_unknown == 1
    assert m.cache_hits == Rate(3, 1)
    assert cost_metrics([]).avg_tokens is None
