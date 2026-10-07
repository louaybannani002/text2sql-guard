"""Turn introspected relations into stored catalog documents (text, hash, structured JSON)."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from text2sql.retrieval.catalog import ColumnInfo, ForeignKey, RelationInfo


@dataclass(frozen=True, slots=True)
class SchemaDoc:
    """The retrieval document for one relation."""

    relation: str
    kind: str
    content: str  # embedded and keyword-indexed
    content_hash: str
    definition: str  # RelationInfo as JSON: the retriever's structured view (FK graph, DDL)


def _fk_line(fk: ForeignKey, *, incoming: bool) -> str:
    cols, ref_cols = ", ".join(fk.columns), ", ".join(fk.ref_columns)
    line = (
        f"- {fk.relation} ({cols}) -> ({ref_cols})"
        if incoming
        else f"- ({cols}) -> {fk.ref_relation} ({ref_cols})"
    )
    return line + (" (inferred join, not a database constraint)" if fk.inferred else "")


def render_document(info: RelationInfo) -> str:
    """Plain-text document for one relation: what the retriever embeds and searches."""
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
        lines += [_fk_line(fk, incoming=False) for fk in info.foreign_keys]
    if info.referenced_by:
        lines += ["", "Referenced by:"]
        lines += [_fk_line(fk, incoming=True) for fk in info.referenced_by]
    return "\n".join(lines) + "\n"


def definition_json(info: RelationInfo) -> str:
    """Stable JSON for a relation (sorted keys, so equal infos give equal text)."""
    return json.dumps(asdict(info), sort_keys=True, ensure_ascii=False)


def relation_from_definition(text: str) -> RelationInfo:
    """Inverse of ``definition_json``."""
    data: dict[str, Any] = json.loads(text)

    def fk(raw: dict[str, Any]) -> ForeignKey:
        return ForeignKey(
            relation=raw["relation"],
            columns=tuple(raw["columns"]),
            ref_relation=raw["ref_relation"],
            ref_columns=tuple(raw["ref_columns"]),
            inferred=bool(raw.get("inferred", False)),
        )

    return RelationInfo(
        name=data["name"],
        kind=data["kind"],
        comment=data["comment"],
        columns=tuple(
            ColumnInfo(
                name=c["name"],
                type=c["type"],
                nullable=c["nullable"],
                comment=c["comment"],
                examples=None if c["examples"] is None else tuple(c["examples"]),
            )
            for c in data["columns"]
        ),
        foreign_keys=tuple(fk(raw) for raw in data["foreign_keys"]),
        referenced_by=tuple(fk(raw) for raw in data["referenced_by"]),
    )


def to_doc(info: RelationInfo) -> SchemaDoc:
    """Render, hash and serialise one relation.

    The hash covers the rendered text, which shows every field of ``info``, so it changes
    whenever the definition does.
    """
    content = render_document(info)
    return SchemaDoc(info.name, info.kind, content, _sha256(content), definition_json(info))


def schema_version(docs: list[SchemaDoc]) -> str:
    """Hash of the whole catalog: changes iff any document's content changes."""
    payload = json.dumps(sorted((d.relation, d.content_hash) for d in docs))
    return _sha256(payload)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
