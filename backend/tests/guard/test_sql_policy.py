from text2sql.guard.sql_policy import SqlPolicy, policy_from_relations
from text2sql.retrieval.catalog import ColumnInfo, RelationInfo

# load_policy() reads the database: see tests/integration/test_sql_validator.py.


def _relation(name: str, *columns: str) -> RelationInfo:
    return RelationInfo(
        name=name,
        kind="table",
        comment="",
        columns=tuple(
            ColumnInfo(c, "text", nullable=False, comment="", examples=()) for c in columns
        ),
        foreign_keys=(),
        referenced_by=(),
    )


def test_policy_from_relations() -> None:
    policy = policy_from_relations(
        [_relation("shop.customers", "customer_id", "customer_state")],
        {"shop.customers": ["customer_city"], "shop.not_in_catalog": ["x"]},
    )
    assert policy.tables == frozenset({"shop.customers"})
    assert policy.readable_columns["shop.customers"] == {"customer_id", "customer_state"}
    # Restrictions on relations outside the catalog are irrelevant (they cannot be queried).
    assert dict(policy.personal_columns) == {"shop.customers": frozenset({"customer_city"})}
    assert policy.max_rows == 1000


def test_sqlglot_schema_includes_personal_columns_so_they_resolve() -> None:
    policy = SqlPolicy(
        readable_columns={"shop.customers": frozenset({"customer_id"})},
        personal_columns={"shop.customers": frozenset({"customer_city"})},
    )
    assert policy.sqlglot_schema() == {
        "shop": {"customers": {"customer_city": "text", "customer_id": "text"}}
    }
