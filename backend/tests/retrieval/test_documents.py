from dataclasses import replace

from text2sql.retrieval.catalog import ColumnInfo, ForeignKey, RelationInfo
from text2sql.retrieval.documents import (
    SchemaDoc,
    definition_json,
    relation_from_definition,
    render_document,
    schema_version,
    to_doc,
)

ORDERS = RelationInfo(
    name="shop.orders",
    kind="table",
    comment="One row per customer order.",
    columns=(
        ColumnInfo(
            "order_id",
            "shop.olist_id",
            nullable=False,
            comment="Order id.",
            examples=("a", "b", "c"),
        ),
        ColumnInfo(
            "order_status",
            "text",
            nullable=False,
            comment="Lifecycle state.",
            examples=("delivered",),
        ),
        ColumnInfo("note", "text", nullable=True, comment="", examples=None),
    ),
    foreign_keys=(ForeignKey("shop.orders", ("customer_id",), "shop.customers", ("customer_id",)),),
    referenced_by=(ForeignKey("shop.order_items", ("order_id",), "shop.orders", ("order_id",)),),
)


def test_render_document() -> None:
    assert render_document(ORDERS) == (
        "# shop.orders (table)\n"
        "One row per customer order.\n"
        "\n"
        "Columns:\n"
        "- order_id: shop.olist_id, not null. Order id. Examples: 'a', 'b', 'c'.\n"
        "- order_status: text, not null. Lifecycle state. Examples: 'delivered'.\n"
        "- note: text, nullable. (no description) Example values withheld"
        " (free text written by customers).\n"
        "\n"
        "Foreign keys:\n"
        "- (customer_id) -> shop.customers (customer_id)\n"
        "\n"
        "Referenced by:\n"
        "- shop.order_items (order_id) -> (order_id)\n"
    )


def test_relation_without_keys_has_no_key_sections() -> None:
    bare = RelationInfo("shop.x", "materialized view", "", ORDERS.columns[:1], (), ())
    text = render_document(bare)
    assert "(no description)" in text
    assert "Foreign keys" not in text
    assert "Referenced by" not in text


def test_hash_follows_content() -> None:
    changed = replace(ORDERS, comment="Different.")
    assert to_doc(ORDERS).content_hash == to_doc(ORDERS).content_hash
    assert to_doc(ORDERS).content_hash != to_doc(changed).content_hash


def test_schema_version_is_order_independent_and_content_sensitive() -> None:
    a, b = (
        SchemaDoc("shop.a", "table", "x", "h1", "{}"),
        SchemaDoc("shop.b", "table", "y", "h2", "{}"),
    )
    assert schema_version([a, b]) == schema_version([b, a])
    assert schema_version([a, b]) != schema_version(
        [a, SchemaDoc("shop.b", "table", "z", "h3", "{}")]
    )
    assert schema_version([a, b]) != schema_version([a])


def test_inferred_join_is_labelled() -> None:
    view = RelationInfo(
        "shop.customer_person",
        "materialized view",
        "People.",
        ORDERS.columns[:1],
        (
            ForeignKey(
                "shop.customer_person",
                ("customer_id",),
                "shop.customers",
                ("customer_id",),
                inferred=True,
            ),
        ),
        (),
    )
    assert (
        "-> shop.customers (customer_id) (inferred join, not a database constraint)"
        in render_document(view)
    )


def test_definition_round_trips() -> None:
    assert relation_from_definition(definition_json(ORDERS)) == ORDERS
    doc = to_doc(ORDERS)
    assert relation_from_definition(doc.definition) == ORDERS
    assert definition_json(ORDERS) == definition_json(replace(ORDERS))  # stable text
