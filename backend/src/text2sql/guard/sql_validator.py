"""Static validation of generated SQL on the sqlglot AST (postgres dialect). No regex.

``validate(sql, policy)`` either rejects the query with the rule it broke and a reason that is
safe to feed back to the model, or returns it normalised (comments stripped, identifiers
normalised, row limit enforced). Database privileges remain the real wall; this layer gives
precise, early feedback and blocks what privileges cannot express (row limits, functions).
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_rules import DIALECT, RULES
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

MAX_SQL_CHARS = 20_000
RULE_NAMES = ["parse", "single_statement", *(name for name, _ in RULES), "limit"]


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    """A query that passed every rule, rewritten for execution."""

    sql: str
    original: str
    tables: list[str]
    rules_checked: list[str]
    rewrites: list[str]
    row_limit: int


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why a query was refused. ``reason`` is safe to show to the user or the model."""

    rule: str
    reason: str
    rules_checked: list[str]  # rules that passed before this one failed


# ---------------------------------------------------------------- parsing (rule 1)


def _parse(sql: str) -> exp.Expr | Rejection:
    if not sql.strip():
        return Rejection("parse", "The query is empty.", [])
    if len(sql) > MAX_SQL_CHARS:
        return Rejection("parse", f"The query is longer than {MAX_SQL_CHARS} characters.", [])
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError:
        return Rejection("parse", "The query is not valid PostgreSQL.", [])
    if len(statements) != 1:
        reason = f"Expected exactly one statement, got {len(statements)}."
        return Rejection("single_statement", reason, ["parse"])
    # Postgres folds unquoted identifiers to lower case; quoted ones stay as written.
    return normalize_identifiers(statements[0], dialect=DIALECT)


# ---------------------------------------------------------------- row limit


def _enforce_limit(tree: exp.Expr, max_rows: int) -> list[str]:
    """Cap the outer query at ``max_rows`` (in place); returns what was rewritten."""
    existing = tree.args.get("limit")
    count = existing.args.get("count") if isinstance(existing, exp.Fetch) else None
    if isinstance(existing, exp.Limit):
        count = existing.expression
    value = int(count.this) if isinstance(count, exp.Literal) and count.is_int else None
    if value is not None and value <= max_rows:
        if isinstance(existing, exp.Fetch):  # normalise FETCH FIRST n ROWS ONLY to LIMIT n
            tree.set("limit", exp.Limit(expression=exp.Literal.number(value)))
        return []
    tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    if existing is None:
        return [f"added LIMIT {max_rows}"]
    if value is None:
        return [f"replaced a non-constant limit with LIMIT {max_rows}"]
    return [f"lowered LIMIT {value} to {max_rows}"]


# ---------------------------------------------------------------- entry point


def validate(sql: str, policy: SqlPolicy) -> ValidatedSql | Rejection:
    """Check ``sql`` against every rule; return it normalised, or the first rule it breaks."""
    parsed = _parse(sql)
    if isinstance(parsed, Rejection):
        log.warning("sql_rejected", rule=parsed.rule, rules_passed=parsed.rules_checked)
        return parsed
    tree, passed = parsed, ["parse", "single_statement"]
    for name, check in RULES:
        reason = check(tree, policy)
        if reason is not None:
            # Never log the SQL itself: it is model output (CLAUDE.md).
            log.warning("sql_rejected", rule=name, rules_passed=passed)
            return Rejection(rule=name, reason=reason, rules_checked=passed)
        passed.append(name)
    rewrites = _enforce_limit(tree, policy.max_rows)
    passed.append("limit")

    tables = sorted({f"{t.db}.{t.name}" for t in tree.find_all(exp.Table) if t.db})
    log.info("sql_validated", tables=tables, rewrites=rewrites)
    return ValidatedSql(
        sql=tree.sql(dialect=DIALECT, pretty=True, comments=False),
        original=sql,
        tables=tables,
        rules_checked=passed,
        rewrites=rewrites,
        row_limit=policy.max_rows,
    )
