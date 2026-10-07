"""The validator's rules, each a pure function of the AST: a reason to reject, or None.

Order matters only for which reason is reported first; every rule must pass.
"""

from collections.abc import Callable

from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from text2sql.guard.sql_functions import (
    ALLOWED_CAST_TYPES,
    ALLOWED_FUNCTIONS,
    function_name,
    is_denied,
)
from text2sql.guard.sql_policy import SqlPolicy

DIALECT = "postgres"

# Anything that writes, changes structure or privileges, or is not a plain query.
_FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Grant", "Revoke",
        "TruncateTable", "Command", "Copy", "Set", "Transaction", "Commit", "Rollback", "Use",
        "Pragma", "LoadData", "Kill", "Analyze", "Cache", "Uncache", "Refresh", "Comment",
        "Show", "Describe", "Summarize",
    )
    if hasattr(exp, name)
)  # fmt: skip
_SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})

type Check = Callable[[exp.Expr, SqlPolicy], str | None]


def _read_only(tree: exp.Expr, _policy: SqlPolicy) -> str | None:
    if not isinstance(tree, exp.Select | exp.SetOperation):
        return f"Only SELECT queries are allowed, not {tree.key.upper()}."
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):  # also inside CTEs and subqueries
            return f"{node.key.upper()} is not allowed anywhere in the query."
    return None


def _no_into_lock_copy(tree: exp.Expr, _policy: SqlPolicy) -> str | None:
    for node in tree.walk():
        if isinstance(node, exp.Into):
            return "SELECT INTO is not allowed."
        if isinstance(node, exp.Lock):
            return "Row locking (FOR UPDATE / FOR SHARE) is not allowed."
        if isinstance(node, exp.Copy):
            return "COPY is not allowed."
    return None


def _table_problem(table: exp.Table, policy: SqlPolicy) -> str | None:
    """First reason a (non-CTE) table reference is not allowed, in order of precedence."""
    checks = [
        (not isinstance(table.this, exp.Identifier), "Table functions are not allowed in FROM."),
        (
            bool(table.catalog),
            f"Database-qualified names are not allowed ({table.sql(dialect=DIALECT)}).",
        ),
        (
            table.db in _SYSTEM_SCHEMAS or table.name.startswith("pg_"),
            "System catalogs are not allowed.",
        ),
        (
            not table.db,
            f"Table {table.name} must be schema-qualified as {policy.schema}.<table>.",
        ),
        (table.db != policy.schema, f"Only schema {policy.schema} may be queried, not {table.db}."),
        (
            f"{table.db}.{table.name}" not in policy.tables,
            f"Unknown table {table.db}.{table.name}.",
        ),
    ]
    return next((reason for failed, reason in checks if failed), None)


def _tables(tree: exp.Expr, policy: SqlPolicy) -> str | None:
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        is_cte_reference = isinstance(table.this, exp.Identifier) and not table.db
        if is_cte_reference and table.name in ctes:
            continue
        problem = _table_problem(table, policy)
        if problem is not None:
            return problem
    return None


def _no_star(tree: exp.Expr, _policy: SqlPolicy) -> str | None:
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):  # count(*) is not a projection
            return "SELECT * and alias.* are not allowed; list the columns you need."
    return None


def _functions(tree: exp.Expr, _policy: SqlPolicy) -> str | None:
    for func in tree.find_all(exp.Func):
        name = function_name(func)
        if is_denied(name):
            return f"Function {name} is not allowed."
        if name not in ALLOWED_FUNCTIONS:
            return f"Function {name} is not in the list of allowed functions."
    return None


def _casts(tree: exp.Expr, _policy: SqlPolicy) -> str | None:
    for data_type in tree.find_all(exp.DataType):
        if data_type.this not in ALLOWED_CAST_TYPES:
            return f"Casting to {data_type.sql(dialect=DIALECT)} is not allowed."
    return None


def _source(scope: Scope | None, table_alias: str) -> exp.Expr | Scope | None:
    """Resolve a column's table alias, walking out to enclosing scopes (correlated refs)."""
    while scope is not None:
        if table_alias in scope.sources:
            source: exp.Expr | Scope = scope.sources[table_alias]
            return source
        scope = scope.parent
    return None


def _columns(tree: exp.Expr, policy: SqlPolicy) -> str | None:
    try:
        qualified = qualify(
            tree.copy(),
            schema=policy.sqlglot_schema(),
            dialect=DIALECT,
            validate_qualify_columns=True,
            expand_stars=False,
            infer_schema=False,
        )
    except OptimizeError as exc:
        return f"Column check failed: {exc}."
    if any(qualified.find_all(exp.TableColumn)):
        # Postgres reads `SELECT c FROM shop.customers c` as the whole row, every column.
        return "Whole-row references are not allowed; name the columns."
    for scope in traverse_scope(qualified):
        for column in scope.columns:
            source = _source(scope, column.table)
            if source is None:
                return f"Column {column.sql(dialect=DIALECT)} could not be resolved."
            if not isinstance(source, exp.Table):
                continue  # a CTE or subquery output; its own columns are checked in its scope
            relation = f"{source.db}.{source.name}"
            if column.name in policy.personal_columns.get(relation, frozenset()):
                return f"Column {relation}.{column.name} is personal data and not readable."
            if column.name not in policy.readable_columns.get(relation, frozenset()):
                return f"Unknown column {relation}.{column.name}."
    return None


RULES: list[tuple[str, Check]] = [
    ("read_only", _read_only),
    ("no_into_lock_copy", _no_into_lock_copy),
    ("tables", _tables),
    ("no_star", _no_star),
    ("functions", _functions),
    ("casts", _casts),
    ("columns", _columns),
]
