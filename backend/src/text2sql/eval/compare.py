"""Execution accuracy: does a predicted result set equal the gold one?

- Rows are compared as a multiset. When the gold SQL sorts its output, the predicted rows must
  also follow the gold order on the ORDER BY columns; rows that tie on them may come in any
  order (``ordering.order_key_columns``).
- Columns are matched by content, not by name or position: each gold column must map to a
  distinct predicted column. Extra predicted columns are tolerated (e.g. a share added next to
  a count). Gold columns listed as optional (context the question does not ask for, e.g. a
  review count next to an average) may be missing.
- Numbers match at the precision of the less precise side (see ``values``); a column may be
  in percent on one side and a fraction on the other.
- Labels may be renamed (``'0: on time'`` vs ``'on time'``, year ``2017`` vs ``'2017-01-01'``)
  when the numeric columns pair the rows one-to-one (see ``relabel``).
"""

import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from text2sql.eval.relabel import relabelled
from text2sql.eval.values import SCALES, Value, normalize, scaled, values_equal
from text2sql.executor.serialize import JsonValue

_MAX_MAPPINGS = 5000
type Row = tuple[Value, ...]


@dataclass(frozen=True, slots=True)
class Comparison:
    """Whether the results match and, if not, a short reason for the failure report."""

    match: bool
    reason: str


def same_multiset(gold: Sequence[Row], pred: Sequence[Row]) -> bool:
    """Same rows regardless of order, with tolerant values."""
    if len(gold) != len(pred):
        return False
    remaining = list(pred)
    for row in gold:
        index = next(
            (i for i, cand in enumerate(remaining) if all(map(values_equal, row, cand))), None
        )
        if index is None:
            return False
        remaining.pop(index)
    return True


def same_order(gold: Sequence[Row], pred: Sequence[Row], keys: Sequence[int]) -> bool:
    """The ORDER BY columns read the same, row by row (ties may be permuted)."""
    return all(all(values_equal(g[k], p[k]) for k in keys) for g, p in zip(gold, pred, strict=True))


def _mappings(n_gold: int, n_pred: int) -> Iterator[tuple[tuple[int, float], ...]]:
    choices = [(i, s) for s in SCALES for i in range(n_pred)]  # unscaled options first
    combos = itertools.product(choices, repeat=n_gold)
    distinct = (c for c in combos if len({i for i, _ in c}) == n_gold)
    return itertools.islice(distinct, _MAX_MAPPINGS)


def _match(gold: list[Row], pred: list[Row], keys: Sequence[int] | None) -> str | None:
    """'match' / 'match (labels renamed)' / 'row order differs', or None."""
    order_only_failed = False
    for mapping in _mappings(len(gold[0]), len(pred[0])):
        projected = [tuple(scaled(row[i], s) for i, s in mapping) for row in pred]
        for candidate, how in (
            (projected, "match"),
            (relabelled(gold, projected), "match (labels renamed)"),
        ):
            if candidate is None or not same_multiset(gold, candidate):
                continue
            if keys is None or same_order(gold, candidate, keys):
                return how
            order_only_failed = True
    return "row order differs" if order_only_failed else None


def compare_results(
    gold_rows: Sequence[Sequence[JsonValue]],
    pred_rows: Sequence[Sequence[JsonValue]],
    *,
    order_keys: Sequence[int] | None = None,
    optional_columns: Sequence[int] = (),
) -> Comparison:
    """Compare two result sets (see module docstring); ``order_keys`` None = unordered."""
    gold = [tuple(map(normalize, row)) for row in gold_rows]
    pred = [tuple(map(normalize, row)) for row in pred_rows]
    if len(gold) != len(pred):
        return Comparison(match=False, reason=f"row count {len(pred)} != gold {len(gold)}")
    if not gold:
        return Comparison(match=True, reason="both empty")
    keep = [i for i in range(len(gold[0])) if i not in set(optional_columns)]
    attempts: list[tuple[list[Row], Sequence[int] | None, str]] = [(gold, order_keys, "")]
    if optional_columns and keep:
        reduced = [tuple(row[i] for i in keep) for row in gold]
        reduced_keys = (
            None if order_keys is None else [keep.index(k) for k in order_keys if k in keep]
        )
        attempts.append((reduced, reduced_keys, " (without optional columns)"))
    order_failed = False
    for attempt, keys, suffix in attempts:
        if len(pred[0]) < len(attempt[0]):
            continue
        outcome = _match(attempt, pred, keys)
        if outcome is not None and outcome.startswith("match"):
            return Comparison(match=True, reason=outcome + suffix)
        order_failed = order_failed or outcome == "row order differs"
    if order_failed:
        return Comparison(match=False, reason="row order differs")
    needed = len(attempts[-1][0][0])
    if len(pred[0]) < needed:
        return Comparison(match=False, reason=f"{len(pred[0])} columns, gold needs {needed}")
    return Comparison(match=False, reason="values differ")
