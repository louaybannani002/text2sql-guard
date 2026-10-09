import pytest

from text2sql.eval.compare import compare_results
from text2sql.eval.ordering import order_key_columns
from text2sql.executor.serialize import JsonValue

type Rows = list[list[JsonValue]]


def _match(gold: Rows, pred: Rows, **kwargs: object) -> bool:
    return compare_results(gold, pred, **kwargs).match  # type: ignore[arg-type]  # test helper


GOLD: Rows = [["delivered", 96478], ["shipped", 1107], ["canceled", 625]]


def test_identical_and_reordered_rows_match_when_unordered() -> None:
    assert _match(GOLD, GOLD)
    assert _match(GOLD, list(reversed(GOLD)))


def test_columns_are_matched_by_content_and_extra_ones_are_tolerated() -> None:
    pred: Rows = [[96478, "delivered", 0.97], [1107, "shipped", 0.01], [625, "canceled", 0.006]]
    result = compare_results(GOLD, pred)
    assert (result.match, result.reason) == (True, "match")


@pytest.mark.parametrize(
    ("pred", "reason"),
    [
        ([["delivered", 96478], ["shipped", 1107]], "row count 2 != gold 3"),
        ([["delivered", 96478], ["shipped", 1107], ["canceled", 626]], "values differ"),
        ([[96478], [1107], [625]], "1 columns, gold needs 2"),
    ],
)
def test_wrong_results_fail_with_a_reason(pred: Rows, reason: str) -> None:
    result = compare_results(GOLD, pred)
    assert (result.match, result.reason) == (False, reason)


def test_precision_rounding_and_number_formats() -> None:
    assert _match([[2276]], [[2276.47]])  # gold rounded to units
    assert _match([[0.8]], [[0.75]])  # Postgres rounds half away from zero
    assert _match([[4.08]], [[4.1]])
    assert _match([[1234.5]], [["1234.50"]])  # numeric serialised as text
    assert not _match([[4.08]], [[4.2]])
    assert not _match([[2276]], [[2277.6]])


def test_percent_versus_fraction() -> None:
    assert _match([["2017-02-01", 109.5]], [["2017-02-01", 1.0950521993]])
    assert not _match([["2017-02-01", 109.5]], [["2017-02-01", 1.2]])


def test_dates_and_midnight_timestamps_are_equal() -> None:
    assert _match([["2017-01-01", 5]], [["2017-01-01T00:00:00+00:00", 5]])


def test_labels_may_be_renamed_when_numbers_pair_the_rows() -> None:
    gold: Rows = [["0: on time", 89949, 4.29], ["1: 1-3 days late", 1856, 3.29]]
    pred: Rows = [["on time", 89949, 4.29], ["1-3 days late", 1856, 3.29]]
    assert compare_results(gold, pred).reason == "match (labels renamed)"
    years: Rows = [[2016, 329], [2017, 45101]]
    assert _match(years, [["2016-01-01", 329], ["2017-01-01", 45101]])


def test_shared_labels_can_never_be_swapped() -> None:
    gold: Rows = [["SP", 4.1], ["RJ", 4.0]]
    assert not _match(gold, [["RJ", 4.1], ["SP", 4.0]])
    assert not _match(gold, [["RJ", 4.1], ["SP", 4.0]], order_keys=[1])


def test_labels_alone_prove_nothing() -> None:
    assert not _match([["a"], ["b"]], [["x"], ["y"]])


def test_order_is_checked_on_the_sort_columns_only() -> None:
    gold: Rows = [["AP", 4.19], ["PR", 4.18], ["AM", 4.18]]
    tie_swapped: Rows = [["AP", 4.19], ["AM", 4.18], ["PR", 4.18]]
    assert _match(gold, tie_swapped, order_keys=[1])
    wrong_order: Rows = [["PR", 4.18], ["AP", 4.19], ["AM", 4.18]]
    result = compare_results(gold, wrong_order, order_keys=[1])
    assert (result.match, result.reason) == (False, "row order differs")
    assert _match(gold, wrong_order)  # unordered gold: any order


def test_optional_columns_may_be_missing_but_required_ones_may_not() -> None:
    gold: Rows = [["SP", 4.1, 5000], ["RJ", 4.0, 1200]]
    pred: Rows = [["SP", 4.1], ["RJ", 4.0]]
    result = compare_results(gold, pred, optional_columns=[2])
    assert (result.match, result.reason) == (True, "match (without optional columns)")
    assert not _match(gold, pred)
    assert not _match(gold, [["SP", 5000], ["RJ", 1200]], optional_columns=[2])


def test_empty_results() -> None:
    assert _match([], [])
    assert not _match([], [[1]])


@pytest.mark.parametrize(
    ("sql", "keys"),
    [
        ("SELECT a.x, count(*) AS n FROM t AS a GROUP BY 1", None),
        ("SELECT a.x, count(*) AS n FROM t AS a GROUP BY 1 ORDER BY n DESC", [1]),
        ("SELECT a.x, count(*) AS n FROM t AS a GROUP BY 1 ORDER BY 2 DESC, 1", [1, 0]),
        ("SELECT a.x, count(*) AS n FROM t AS a GROUP BY a.x ORDER BY a.x", [0]),
        ("SELECT a.x FROM t AS a ORDER BY a.y", [0]),  # unresolvable: every column
        ("WITH c AS (SELECT 1 AS v ORDER BY 1) SELECT c.v FROM c", None),
    ],
)
def test_order_key_columns(sql: str, keys: list[int] | None) -> None:
    assert order_key_columns(sql) == keys
