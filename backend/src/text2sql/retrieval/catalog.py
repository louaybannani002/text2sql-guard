"""Introspect schema ``shop`` into one retrieval document per relation.

Only what ``t2s_reader`` may read is described (CLAUDE.md: restricted columns never reach a
prompt). Relations include views and materialized views. Must run as ``t2s_owner`` (to sample
values) with ``search_path = pg_catalog`` (so type names, hence hashes, are deterministic).
"""

import hashlib
import json
from dataclasses import dataclass

import asyncpg

from text2sql.db.roles import READER_ROLE

SCHEMA = "shop"
EXAMPLE_VALUES = 3
MAX_VALUE_CHARS = 60

# Readable by t2s_reader, but free text written by customers: may contain personal data, so
# never sampled into documents.
NO_EXAMPLE_VALUES: frozenset[tuple[str, str]] = frozenset(
    {
        ("order_reviews", "review_comment_title"),
        ("order_reviews", "review_comment_message"),
    }
)

_KINDS = {"r": "table", "p": "table", "v": "view", "m": "materialized view"}


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """A column the query role can read."""

    name: str
    type: str
    nullable: bool
    comment: str
    examples: tuple[str, ...] | None  # None: deliberately withheld


@dataclass(frozen=True, slots=True)
class ForeignKey:
    """``relation.columns -> ref_relation.ref_columns``."""

    relation: str
    columns: tuple[str, ...]
    ref_relation: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationInfo:
    """Everything a document says about one relation."""

    name: str  # schema-qualified, e.g. shop.orders
    kind: str
    comment: str
    columns: tuple[ColumnInfo, ...]
    foreign_keys: tuple[ForeignKey, ...]  # outgoing
    referenced_by: tuple[ForeignKey, ...]  # incoming


@dataclass(frozen=True, slots=True)
class SchemaDoc:
    """The retrieval document for one relation."""

    relation: str
    kind: str
    content: str
    content_hash: str


_RELATIONS = """
SELECT c.oid, c.relname, c.relkind::text AS relkind,
       coalesce(obj_description(c.oid, 'pg_class'), '') AS comment
FROM pg_class c
WHERE c.relnamespace = $1::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm')
ORDER BY c.relname
"""

_COLUMNS = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
       coalesce(col_description(a.attrelid, a.attnum), '') AS comment
FROM pg_attribute a
WHERE a.attrelid = $1 AND a.attnum > 0 AND NOT a.attisdropped
  AND has_column_privilege($2, a.attrelid, a.attnum, 'SELECT')
ORDER BY a.attnum
"""

_FOREIGN_KEYS = """
SELECT c.conname,
       format('%I.%I', sn.nspname, src.relname) AS relation,
       format('%I.%I', tn.nspname, tgt.relname) AS ref_relation,
       array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.i)
           AS columns,
       array(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n ORDER BY k.i)
           AS ref_columns
FROM pg_constraint c
JOIN pg_class src ON src.oid = c.conrelid JOIN pg_namespace sn ON sn.oid = src.relnamespace
JOIN pg_class tgt ON tgt.oid = c.confrelid JOIN pg_namespace tn ON tn.oid = tgt.relnamespace
WHERE c.contype = 'f' AND sn.nspname = $1
ORDER BY relation, c.conname
"""


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _example_values(conn: asyncpg.Connection, relation: str, column: str) -> tuple[str, ...]:
    """The most frequent non-null values (ties broken by value): deterministic and typical."""
    col = _ident(column)
    rel = ".".join(_ident(part) for part in relation.split("."))
    rows = await conn.fetch(
        f"SELECT {col}::text AS v FROM {rel} WHERE {col} IS NOT NULL"  # noqa: S608 - quoted catalog names
        f" GROUP BY {col} ORDER BY count(*) DESC, {col} LIMIT {EXAMPLE_VALUES}"
    )
    return tuple(_shorten(row["v"]) for row in rows)


def _shorten(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= MAX_VALUE_CHARS else value[: MAX_VALUE_CHARS - 1] + "…"


async def introspect(conn: asyncpg.Connection, schema: str = SCHEMA) -> list[RelationInfo]:
    """Describe every relation in ``schema`` that the query role can read at least partly."""
    readable: dict[str, tuple[tuple[str, str, str], tuple[ColumnInfo, ...]]] = {}
    for rel in await conn.fetch(_RELATIONS, schema):
        name = f"{schema}.{rel['relname']}"
        columns = []
        for col in await conn.fetch(_COLUMNS, rel["oid"], READER_ROLE):
            withheld = (rel["relname"], col["attname"]) in NO_EXAMPLE_VALUES
            columns.append(
                ColumnInfo(
                    name=col["attname"],
                    type=col["type"],
                    nullable=col["nullable"],
                    comment=col["comment"],
                    examples=None
                    if withheld
                    else await _example_values(conn, name, col["attname"]),
                )
            )
        if columns:
            readable[name] = ((name, _KINDS[rel["relkind"]], rel["comment"]), tuple(columns))

    visible = {name: {c.name for c in cols} for name, (_, cols) in readable.items()}
    fks = [
        ForeignKey(r["relation"], tuple(r["columns"]), r["ref_relation"], tuple(r["ref_columns"]))
        for r in await conn.fetch(_FOREIGN_KEYS, schema)
    ]
    # A join hint is only useful (and only safe to show) if both sides are readable.
    fks = [
        fk
        for fk in fks
        if set(fk.columns) <= visible.get(fk.relation, set())
        and set(fk.ref_columns) <= visible.get(fk.ref_relation, set())
    ]
    return [
        RelationInfo(
            name=name,
            kind=kind,
            comment=comment,
            columns=columns,
            foreign_keys=tuple(fk for fk in fks if fk.relation == name),
            referenced_by=tuple(fk for fk in fks if fk.ref_relation == name),
        )
        for name, ((_, kind, comment), columns) in readable.items()
    ]


def render_document(info: RelationInfo) -> str:
    """Plain-text document for one relation: what the LLM and the retriever see."""
    lines = [f"# {info.name} ({info.kind})", info.comment or "(no description)", "", "Columns:"]
    for col in info.columns:
        null = "nullable" if col.nullable else "not null"
        line = f"- {col.name}: {col.type}, {null}. {col.comment or '(no description)'}"
        if col.examples is None:
            line += " Example values withheld (free text written by customers)."
        elif col.examples:
            line += " Examples: " + ", ".join(repr(v) for v in col.examples) + "."
        lines.append(line)
    if info.foreign_keys:
        lines += ["", "Foreign keys:"]
        lines += [
            f"- ({', '.join(fk.columns)}) -> {fk.ref_relation} ({', '.join(fk.ref_columns)})"
            for fk in info.foreign_keys
        ]
    if info.referenced_by:
        lines += ["", "Referenced by:"]
        lines += [
            f"- {fk.relation} ({', '.join(fk.columns)}) -> ({', '.join(fk.ref_columns)})"
            for fk in info.referenced_by
        ]
    return "\n".join(lines) + "\n"


def to_doc(info: RelationInfo) -> SchemaDoc:
    """Render and hash one relation."""
    content = render_document(info)
    return SchemaDoc(info.name, info.kind, content, _sha256(content))


def schema_version(docs: list[SchemaDoc]) -> str:
    """Hash of the whole catalog: changes iff any document's content changes."""
    payload = json.dumps(sorted((d.relation, d.content_hash) for d in docs))
    return _sha256(payload)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
