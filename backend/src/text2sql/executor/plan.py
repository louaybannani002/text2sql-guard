"""EXPLAIN (FORMAT JSON) parsing and the cost/row admission check.

The row check uses the LARGEST estimate of ANY plan node, not the top node: the validator caps
the outer query at 1000 rows, and a LIMIT also makes the top node's cost tiny, so only the
inner nodes reveal a cross-join or self-join blow-up (e.g. 11 billion rows under a LIMIT 1000).
"""

import json
from dataclasses import dataclass
from typing import Any

from text2sql.executor.errors import QueryTooExpensiveError


@dataclass(frozen=True, slots=True)
class PlanEstimate:
    """What the planner expects the query to cost."""

    total_cost: float  # top node, in Postgres cost units
    max_rows: int  # largest row estimate among all plan nodes


def _max_rows(node: dict[str, Any]) -> int:
    rows = int(node.get("Plan Rows", 0))
    return max([rows, *(_max_rows(child) for child in node.get("Plans", []))])


def parse_explain(explain_json: str | list[Any]) -> PlanEstimate:
    """Read the estimates from ``EXPLAIN (FORMAT JSON)`` output (text or decoded)."""
    data = json.loads(explain_json) if isinstance(explain_json, str) else explain_json
    plan: dict[str, Any] = data[0]["Plan"]
    return PlanEstimate(total_cost=float(plan["Total Cost"]), max_rows=_max_rows(plan))


def check_estimate(estimate: PlanEstimate, *, max_cost: float, max_rows: int) -> None:
    """Raise ``QueryTooExpensiveError`` if the plan exceeds either threshold."""
    if estimate.total_cost > max_cost:
        msg = (
            f"The query is too expensive (estimated cost {estimate.total_cost:,.0f} > "
            f"{max_cost:,.0f}). Narrow it with filters or aggregate earlier."
        )
    elif estimate.max_rows > max_rows:
        msg = (
            f"The query would process too many rows (estimated {estimate.max_rows:,} > "
            f"{max_rows:,}), usually a missing join condition."
        )
    else:
        return
    raise QueryTooExpensiveError(
        msg, estimated_cost=estimate.total_cost, estimated_rows=estimate.max_rows
    )
