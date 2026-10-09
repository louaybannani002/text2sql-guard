from text2sql.eval.relabel import relabelled
from text2sql.eval.values import Value

type Rows = list[tuple[Value, ...]]


def test_renames_labels_to_the_gold_names() -> None:
    gold: Rows = [("0: early", 10.0), ("1: late", 3.0)]
    pred: Rows = [("late", 3.0), ("early", 10.0)]
    assert relabelled(gold, pred) == [("1: late", 3.0), ("0: early", 10.0)]


def test_ambiguous_anchors_refuse_to_pair() -> None:
    gold: Rows = [("a", 1.0), ("b", 1.0)]
    assert relabelled(gold, [("x", 1.0), ("y", 1.0)]) is None


def test_a_name_used_on_both_sides_keeps_its_meaning() -> None:
    gold: Rows = [("SP", 2.0), ("RJ", 1.0)]
    assert relabelled(gold, [("RJ", 2.0), ("SP", 1.0)]) is None


def test_two_gold_labels_cannot_merge_into_one() -> None:
    gold: Rows = [("a", 1.0), ("b", 2.0)]
    assert relabelled(gold, [("x", 1.0), ("x", 2.0)]) is None


def test_needs_a_numeric_anchor() -> None:
    assert relabelled([("a", "b")], [("x", "y")]) is None


def test_nothing_to_rename() -> None:
    assert relabelled([("a", 1.0)], [("a", 1.0)]) is None
    assert relabelled([], []) is None
