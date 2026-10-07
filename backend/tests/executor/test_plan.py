import json

import pytest

from text2sql.executor.errors import QueryTooExpensiveError
from text2sql.executor.plan import PlanEstimate, check_estimate, parse_explain

# A LIMIT over a cross join: cheap at the top, enormous underneath.
LIMITED_CROSS_JOIN = [
    {
        "Plan": {
            "Node Type": "Limit",
            "Total Cost": 12.4,
            "Plan Rows": 1000,
            "Plans": [
                {
                    "Node Type": "Nested Loop",
                    "Total Cost": 140_000_000.0,
                    "Plan Rows": 11_202_028_650,
                    "Plans": [
                        {"Node Type": "Seq Scan", "Total Cost": 2000.0, "Plan Rows": 99_441},
                        {"Node Type": "Materialize", "Total Cost": 4000.0, "Plan Rows": 112_650},
                    ],
                }
            ],
        }
    }
]


def test_parses_top_cost_and_the_largest_node_estimate() -> None:
    estimate = parse_explain(json.dumps(LIMITED_CROSS_JOIN))
    assert estimate == PlanEstimate(total_cost=12.4, max_rows=11_202_028_650)


def test_accepts_already_decoded_json() -> None:
    assert parse_explain(LIMITED_CROSS_JOIN).max_rows == 11_202_028_650


def test_within_thresholds_passes() -> None:
    check_estimate(PlanEstimate(28_224.0, 113_473), max_cost=1_000_000, max_rows=10_000_000)


def test_cost_over_threshold_is_rejected() -> None:
    with pytest.raises(QueryTooExpensiveError, match="too expensive") as caught:
        check_estimate(PlanEstimate(296_333_776.0, 50), max_cost=1_000_000, max_rows=10_000_000)
    assert caught.value.estimated_cost == 296_333_776.0


def test_rows_over_threshold_are_rejected_even_when_cost_is_tiny() -> None:
    with pytest.raises(QueryTooExpensiveError, match="too many rows") as caught:
        check_estimate(parse_explain(LIMITED_CROSS_JOIN), max_cost=1_000_000, max_rows=10_000_000)
    assert caught.value.estimated_rows == 11_202_028_650
