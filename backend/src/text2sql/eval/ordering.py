"""Which output columns the gold SQL sorts by, so ties may come in any order."""

import sqlglot
from sqlglot import exp


def order_key_columns(sql: str) -> list[int] | None:
    """Output-column indexes of the outermost ORDER BY; None when the result is unordered.

    ORDER BY items are resolved by position (``ORDER BY 1``), alias or identical expression.
    When one cannot be resolved (e.g. a column not in the output), every column becomes a key:
    the comparison is then strictly positional, which is never more lenient.
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(tree, exp.Query):
        return None
    order = tree.args.get("order")
    if order is None:
        return None
    selects = tree.selects
    names = [e.alias_or_name for e in selects]
    expressions = [(e.this if isinstance(e, exp.Alias) else e).sql() for e in selects]
    keys: list[int] = []
    for item in order.expressions:
        target = item.this
        if isinstance(target, exp.Literal) and target.is_int:
            keys.append(int(target.this) - 1)
        elif isinstance(target, exp.Column) and not target.table and target.name in names:
            keys.append(names.index(target.name))
        elif target.sql() in expressions:
            keys.append(expressions.index(target.sql()))
        else:
            return list(range(len(names)))
    return keys
