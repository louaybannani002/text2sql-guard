from text2sql.retrieval.catalog import ColumnInfo, ForeignKey, RelationInfo
from text2sql.retrieval.render import render_relation, render_within_budget

ORDERS = RelationInfo(
    name="shop.orders",
    kind="table",
    comment="One row per order.",
    columns=(
        ColumnInfo(
            "order_id", "shop.olist_id", nullable=False, comment="Order id.", examples=("x",)
        ),
        ColumnInfo(
            "customer_id", "shop.olist_id", nullable=False, comment="Buyer.", examples=("y",)
        ),
        ColumnInfo(
            "order_status",
            "text",
            nullable=False,
            comment="State.",
            examples=("delivered", "shipped"),
        ),
        ColumnInfo("note", "text", nullable=True, comment="Free text.", examples=None),
    ),
    foreign_keys=(ForeignKey("shop.orders", ("customer_id",), "shop.customers", ("customer_id",)),),
    referenced_by=(),
)
CUSTOMERS = RelationInfo(
    name="shop.customers",
    kind="table",
    comment="Buyer of one order.",
    columns=(
        ColumnInfo("customer_id", "shop.olist_id", nullable=False, comment="Id.", examples=("z",)),
    ),
    foreign_keys=(),
    referenced_by=(),
)
PERSON = RelationInfo(
    name="shop.customer_person",
    kind="materialized view",
    comment="",
    columns=(ColumnInfo("customer_id", "shop.olist_id", nullable=False, comment="", examples=()),),
    foreign_keys=(
        ForeignKey(
            "shop.customer_person",
            ("customer_id",),
            "shop.customers",
            ("customer_id",),
            inferred=True,
        ),
    ),
    referenced_by=(),
)


def _chars(text: str) -> int:
    return len(text)


def test_render_relation_full() -> None:
    assert render_relation(ORDERS, "full", {"shop.orders", "shop.customers"}) == (
        "-- One row per order.\n"
        "CREATE TABLE shop.orders (\n"
        "  order_id shop.olist_id NOT NULL, -- Order id.\n"
        "  customer_id shop.olist_id NOT NULL, -- Buyer.\n"
        "  order_status text NOT NULL, -- State. e.g. 'delivered', 'shipped'\n"
        "  note text, -- Free text.\n"
        "  FOREIGN KEY (customer_id) REFERENCES shop.customers (customer_id)\n"
        ");"
    )


def test_foreign_keys_to_absent_relations_are_hidden() -> None:
    text = render_relation(ORDERS, "full", {"shop.orders"})
    assert "FOREIGN KEY" not in text
    assert "  note text -- Free text.\n);" in text  # no dangling comma


def test_detail_levels() -> None:
    no_examples = render_relation(ORDERS, "no_examples", {"shop.orders"})
    assert "e.g." not in no_examples
    assert "-- State." in no_examples
    columns_only = render_relation(ORDERS, "columns_only", {"shop.orders"})
    assert "-- State." not in columns_only
    assert columns_only.startswith("-- One row per order.")  # table comment kept


def test_inferred_join_is_a_comment_not_a_constraint() -> None:
    text = render_relation(PERSON, "full", {"shop.customer_person", "shop.customers"})
    assert text.startswith("CREATE MATERIALIZED VIEW shop.customer_person (")
    assert "  -- joins shop.customers (customer_id) on (customer_id)" in text
    assert "FOREIGN KEY" not in text


def test_within_budget_keeps_everything_when_it_fits() -> None:
    text, details, tokens = render_within_budget([ORDERS, CUSTOMERS], 10_000, _chars)
    assert details == ["full", "full"]
    assert tokens == len(text)


def test_budget_strips_detail_from_least_relevant_first() -> None:
    _, _, full_tokens = render_within_budget([CUSTOMERS, ORDERS], 10_000, _chars)
    text, details, tokens = render_within_budget([CUSTOMERS, ORDERS], full_tokens - 1, _chars)
    # One token short: only the less relevant relation (ORDERS) loses its sample values.
    assert details == ["full", "no_examples"]
    assert "e.g." not in text
    assert tokens < full_tokens


def test_budget_drops_relations_but_never_the_first() -> None:
    text, details, _ = render_within_budget([ORDERS, CUSTOMERS, PERSON], 1, _chars)
    assert details == ["columns_only", "dropped", "dropped"]
    assert "shop.orders" in text
    assert "shop.customers" not in text
    assert "FOREIGN KEY" not in text  # its target was dropped
