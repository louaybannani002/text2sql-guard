"""Match result sets whose labels differ but whose numbers agree row for row.

A gold column is a *label* when its values are strings, or whole numbers shown as text on the
predicted side (year 2017 vs '2017-01-01'). Every other column is an *anchor* and must match.
Rows are paired through the anchors (each pairing must be unambiguous); each label column must
then rename gold values to predicted values one-to-one, and a value present on both sides must
keep its name ('SP' may never become 'RJ'). Without a numeric anchor nothing is relabelled.
"""

from collections.abc import Sequence

from text2sql.eval.values import Value, values_equal

type Row = tuple[Value, ...]


def _is_label(gold_col: list[Value], pred_col: list[Value]) -> bool:
    present = [v for v in gold_col if v is not None]
    text = all(isinstance(v, str) for v in present)
    whole_vs_text = all(isinstance(v, float) and v == int(v) for v in present) and all(
        isinstance(v, str) for v in pred_col if v is not None
    )
    return text or whole_vs_text


def _pairs(gold: Sequence[Row], pred: Sequence[Row], anchors: list[int]) -> list[int] | None:
    """For each gold row, the index of its predicted row (unique match on the anchors)."""
    taken: set[int] = set()
    pairing = []
    for row in gold:
        matches = [
            i for i, cand in enumerate(pred) if all(values_equal(row[c], cand[c]) for c in anchors)
        ]
        if len(matches) != 1 or matches[0] in taken:
            return None  # missing or ambiguous: the anchors do not identify the row
        taken.add(matches[0])
        pairing.append(matches[0])
    return pairing


def _renaming(
    gold: Sequence[Row], pred: Sequence[Row], pairing: list[int], col: int
) -> dict[Value, Value] | None:
    """Pred value -> gold value for one label column, or None if not a valid renaming."""
    gold_values = {row[col] for row in gold}
    pred_values = {row[col] for row in pred}
    back: dict[Value, Value] = {}
    forward: dict[Value, Value] = {}
    for g_row, p_index in zip(gold, pairing, strict=True):
        g, p = g_row[col], pred[p_index][col]
        if (g in pred_values or p in gold_values) and g != p:
            return None  # a name both sides use must refer to the same row
        if back.setdefault(p, g) != g or forward.setdefault(g, p) != p:
            return None
    return back


def relabelled(gold: Sequence[Row], pred: Sequence[Row]) -> list[Row] | None:
    """``pred`` with its labels renamed to the gold names, or None if that is not allowed."""
    if not gold or len(gold) != len(pred):
        return None
    width = len(gold[0])
    labels = [
        c
        for c in range(width)
        if _is_label([r[c] for r in gold], [r[c] for r in pred])
        and {r[c] for r in gold} != {r[c] for r in pred}
    ]
    anchors = [c for c in range(width) if c not in labels]
    if not labels or not any(isinstance(gold[0][c], float) for c in anchors):
        return None
    pairing = _pairs(gold, pred, anchors)
    if pairing is None:
        return None
    renamings = {}
    for col in labels:
        renaming = _renaming(gold, pred, pairing, col)
        if renaming is None:
            return None
        renamings[col] = renaming
    return [
        tuple(renamings[c].get(v, v) if c in renamings else v for c, v in enumerate(row))
        for row in pred
    ]
