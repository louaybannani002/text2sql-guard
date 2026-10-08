"""The validator's rules, each a pure function of the AST: a ``Violation``, or None.

Every violation is classified. ``security=True`` means the query tried something it must never
do (write, read system catalogs or personal data, call a dangerous function): the pipeline must
not ask the model to "fix" it. Otherwise the query is merely wrong (unknown column, ``*``,
missing schema) and a retry with the reason as feedback is reasonable.
"""

from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class Violation:
    """Why a rule failed, and whether it is a security problem (never retried)."""

    reason: str
    security: bool


def _security(reason: str) -> Violation:
    return Violation(reason, security=True)


def _fixable(reason: str) -> Violation:
    return Violation(reason, security=False)


type Check = Callable[[exp.Expr, SqlPolicy], Violation | None]


def _read_only(tree: exp.Expr, _policy: SqlPolicy) -> Violation | None:
    if not isinstance(tree, exp.Select | exp.SetOperation):
        return _security(f"Only SELECT queries are allowed, not {tree.key.upper()}.")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):  # also inside CTEs and subqueries
            return _security(f"{node.key.upper()} is not allowed anywhere in the query.")
    return None


def _no_into_lock_copy(tree: exp.Expr, _policy: SqlPolicy) -> Violation | None:
    for node in tree.walk():
        if isinstance(node, exp.Into):
            return _security("SELECT INTO is not allowed.")
        if isinstance(node, exp.Lock):
            return _security("Row locking (FOR UPDATE / FOR SHARE) is not allowed.")
        if isinstance(node, exp.Copy):
            return _security("COPY is not allowed.")
    return None


def _table_problem(table: exp.Table, policy: SqlPolicy) -> Violation | None:
    """First reason a (non-CTE) table reference is not allowed, in order of precedence."""
    checks = [
        (
            not isinstance(table.this, exp.Identifier),
            _security("Table functions are not allowed in FROM."),
        ),
        (
            bool(table.catalog),
            _security(f"Database-qualified names are not allowed ({table.sql(dialect=DIALECT)})."),
        ),
        (
            table.db in _SYSTEM_SCHEMAS or table.name.startswith("pg_"),
            _security("System catalogs are not allowed."),
        ),
        (
            not table.db,
            _fixable(f"Table {table.name} must be schema-qualified as {policy.schema}.<table>."),
        ),
        (
            table.db != policy.schema,
            _security(f"Only schema {policy.schema} may be queried, not {table.db}."),
        ),
        (
            f"{table.db}.{table.name}" not in policy.tables,
            _fixable(f"Unknown table {table.db}.{table.name}."),
        ),
    ]
    return next((violation for failed, violation in checks if failed), None)


def _tables(tree: exp.Expr, policy: SqlPolicy) -> Violation | None:
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        is_cte_reference = isinstance(table.this, exp.Identifier) and not table.db
        if is_cte_reference and table.name in ctes:
            continue
        problem = _table_problem(table, policy)
        if problem is not None:
            return problem
    return None


def _no_star(tree: exp.Expr, _policy: SqlPolicy) -> Violation | None:
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):  # count(*) is not a projection
            return _fixable("SELECT * and alias.* are not allowed; list the columns you need.")
    return None


def _functions(tree: exp.Expr, _policy: SqlPolicy) -> Violation | None:
    for func in tree.find_all(exp.Func):
        name = function_name(func)
        if is_denied(name):
            return _security(f"Function {name} is not allowed.")
        if name not in ALLOWED_FUNCTIONS:
            return _fixable(f"Function {name} is not in the list of allowed functions.")
    return None


def _casts(tree: exp.Expr, _policy: SqlPolicy) -> Violation | None:
    for data_type in tree.find_all(exp.DataType):
        if data_type.this not in ALLOWED_CAST_TYPES:
            # regclass/oid/regproc probe the catalog; json and arrays can pack whole rows.
            return _security(f"Casting to {data_type.sql(dialect=DIALECT)} is not allowed.")
    return None


def _source(scope: Scope | None, table_alias: str) -> exp.Expr | Scope | None:
    """Resolve a column's table alias, walking out to enclosing scopes (correlated refs)."""
    while scope is not None:
        if table_alias in scope.sources:
            source: exp.Expr | Scope = scope.sources[table_alias]
            return source
        scope = scope.parent
    return None


def _columns(tree: exp.Expr, policy: SqlPolicy) -> Violation | None:
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
        return _fixable(f"Column check failed: {exc}.")
    if any(qualified.find_all(exp.TableColumn)):
        # Postgres reads `SELECT c FROM shop.customers c` as the whole row, every column.
        return _security("Whole-row references are not allowed; name the columns.")
    for scope in traverse_scope(qualified):
        for column in scope.columns:
            source = _source(scope, column.table)
            if source is None:
                return _fixable(f"Column {column.sql(dialect=DIALECT)} could not be resolved.")
            if not isinstance(source, exp.Table):
                continue  # a CTE or subquery output; its own columns are checked in its scope
            relation = f"{source.db}.{source.name}"
            if column.name in policy.personal_columns.get(relation, frozenset()):
                return _security(
                    f"Column {relation}.{column.name} is personal data and not readable."
                )
            if column.name not in policy.readable_columns.get(relation, frozenset()):
                return _fixable(f"Unknown column {relation}.{column.name}.")
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
