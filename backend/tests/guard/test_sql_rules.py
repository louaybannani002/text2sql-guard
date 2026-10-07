import sqlglot

from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_rules import RULES

# End-to-end behaviour of every rule is in test_sql_validator.py; this checks the rule table
# itself and that each rule is a pure function of (tree, policy).

POLICY = SqlPolicy(readable_columns={"shop.orders": frozenset({"order_id", "order_status"})})
CHECKS = dict(RULES)


def _tree(sql: str) -> sqlglot.exp.Expr:
    return sqlglot.parse_one(sql, read="postgres")


def test_rule_order() -> None:
    assert [name for name, _ in RULES] == [
        "read_only",
        "no_into_lock_copy",
        "tables",
        "no_star",
        "functions",
        "casts",
        "columns",
    ]


def test_every_rule_passes_a_clean_query() -> None:
    tree = _tree("SELECT o.order_id FROM shop.orders AS o WHERE o.order_status = 'delivered'")
    assert {name: check(tree, POLICY) for name, check in RULES} == dict.fromkeys(CHECKS)


def test_rules_return_a_reason_instead_of_raising() -> None:
    assert CHECKS["no_star"](_tree("SELECT * FROM shop.orders"), POLICY) is not None
    assert CHECKS["tables"](_tree("SELECT x.a FROM public.x AS x"), POLICY) is not None
    assert CHECKS["casts"](_tree("SELECT 1::regclass"), POLICY) is not None


def test_rules_do_not_mutate_the_tree() -> None:
    tree = _tree("SELECT o.order_id FROM shop.orders AS o")
    before = tree.sql()
    for _, check in RULES:
        check(tree, POLICY)
    assert tree.sql() == before  # the column check qualifies a copy
