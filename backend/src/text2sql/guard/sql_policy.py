"""What generated SQL may touch: readable tables/columns and personal-data columns.

Derived from the database (CLAUDE.md: never a hard-coded list): readable columns from the
retrieval catalog (``app.schema_docs``), personal-data columns from ``t2s_reader``'s actual
column privileges. Both queries work as ``t2s_app``.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from text2sql.db.connection import Queryable
from text2sql.db.roles import READER_ROLE
from text2sql.retrieval.catalog import RelationInfo
from text2sql.retrieval.documents import relation_from_definition

SCHEMA = "shop"
MAX_ROWS = 1000

_DEFINITIONS = "SELECT definition::text AS definition FROM app.schema_docs"
# Columns of shop relations the query role may NOT read (pg_catalog is readable by everyone).
_RESTRICTED = """
SELECT format('%I.%I', n.nspname, c.relname) AS relation, a.attname AS column_name
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p', 'v', 'm')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND NOT has_column_privilege($2, c.oid, a.attnum, 'SELECT')
"""


@dataclass(frozen=True, slots=True)
class SqlPolicy:
    """Allowlists for the SQL validator. Relation keys are ``schema.table``."""

    readable_columns: Mapping[str, frozenset[str]]
    personal_columns: Mapping[str, frozenset[str]] = field(default_factory=dict)
    schema: str = SCHEMA
    max_rows: int = MAX_ROWS

    @property
    def tables(self) -> frozenset[str]:
        """Relations that may appear in FROM / JOIN."""
        return frozenset(self.readable_columns)

    def sqlglot_schema(self) -> dict[str, object]:
        """``{schema: {table: {column: type}}}`` for sqlglot's qualifier.

        Personal columns are included on purpose: they must *resolve* so the validator can
        reject them by name instead of reporting an unknown column.
        """
        tables: dict[str, dict[str, str]] = {}
        for relation in sorted(self.tables):
            _, table = relation.split(".", 1)
            columns = self.readable_columns[relation] | self.personal_columns.get(relation, set())
            tables[table] = dict.fromkeys(sorted(columns), "text")
        return {self.schema: tables}


def policy_from_relations(
    relations: Iterable[RelationInfo], personal_columns: Mapping[str, Iterable[str]]
) -> SqlPolicy:
    """Build a policy from catalog relations and the restricted columns per relation."""
    readable = {info.name: frozenset(c.name for c in info.columns) for info in relations}
    personal = {
        relation: frozenset(columns)
        for relation, columns in personal_columns.items()
        if relation in readable
    }
    return SqlPolicy(readable_columns=readable, personal_columns=personal)


async def load_policy(conn: Queryable) -> SqlPolicy:
    """Read the current policy from the catalog and the live column privileges."""
    relations = [relation_from_definition(r["definition"]) for r in await conn.fetch(_DEFINITIONS)]
    personal: dict[str, set[str]] = {}
    for row in await conn.fetch(_RESTRICTED, SCHEMA, READER_ROLE):
        personal.setdefault(row["relation"], set()).add(row["column_name"])
    return policy_from_relations(relations, personal)
