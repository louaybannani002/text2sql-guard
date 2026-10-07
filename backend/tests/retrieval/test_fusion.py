import pytest

from text2sql.retrieval.fusion import (
    RRF_K,
    build_graph,
    expand_join_paths,
    reciprocal_rank_fusion,
)

# The shop foreign-key graph (plus the inferred customer_person -> customers join).
SHOP = build_graph(
    [
        ("products", "product_categories"),
        ("orders", "customers"),
        ("order_items", "orders"),
        ("order_items", "products"),
        ("order_items", "sellers"),
        ("order_payments", "orders"),
        ("order_reviews", "orders"),
        ("customer_person", "customers"),
    ]
)


def test_rrf_scores() -> None:
    fused = dict(reciprocal_rank_fusion({"vector": ["a", "b"], "text": ["b", "c"]}))
    assert fused["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused["a"] == pytest.approx(1 / (RRF_K + 1))
    assert fused["c"] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_rewards_agreement_and_breaks_ties_by_name() -> None:
    fused = reciprocal_rank_fusion({"vector": ["x", "a", "b"], "text": ["y", "b", "a"]})
    # a and b are found by both searches (2/62-ish) and beat x and y, each top of one list
    # (1/61). Equal scores are ordered by name.
    assert [item for item, _ in fused] == ["a", "b", "x", "y"]


def test_rrf_handles_empty_rankings() -> None:
    assert reciprocal_rank_fusion({"vector": [], "text": []}) == []
    assert [i for i, _ in reciprocal_rank_fusion({"vector": ["a"], "text": []})] == ["a"]


def test_graph_is_undirected() -> None:
    assert "orders" in SHOP["customers"]
    assert "customers" in SHOP["orders"]


@pytest.mark.parametrize(
    ("selected", "added"),
    [
        (["orders", "customers"], []),  # directly joined
        (["orders", "products"], ["order_items"]),
        (["sellers", "order_reviews"], ["order_items", "orders"]),
        (["customer_person", "orders"], ["customers"]),  # via the inferred view join
        (["product_categories", "customers"], ["products", "order_items", "orders"]),
        (["orders"], []),
        ([], []),
    ],
)
def test_expansion_adds_the_join_path(selected: list[str], added: list[str]) -> None:
    assert expand_join_paths(selected, SHOP) == added


def test_unreachable_relation_is_kept_and_adds_nothing() -> None:
    assert expand_join_paths(["orders", "geolocations"], SHOP) == []


def test_relations_already_on_the_path_are_not_added() -> None:
    # order_items is both selected and on the orders<->products path.
    assert expand_join_paths(["orders", "products", "order_items"], SHOP) == []


def test_expansion_connects_through_earlier_additions() -> None:
    # sellers needs order_items; products then hangs off order_items directly.
    assert expand_join_paths(["sellers", "orders", "products"], SHOP) == ["order_items"]
