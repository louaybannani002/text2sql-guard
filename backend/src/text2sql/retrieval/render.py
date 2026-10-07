"""Render relations as compact CREATE TABLE-style text that fits a token budget."""

from collections.abc import Callable, Sequence
from typing import Literal

from text2sql.retrieval.catalog import ColumnInfo, RelationInfo

type Detail = Literal["full", "no_examples", "columns_only", "dropped"]
type TokenCounter = Callable[[str], int]

# Opaque identifiers: sample values cost tokens and teach the model nothing.
_NO_SAMPLE_TYPES = frozenset({"shop.olist_id"})
_KEYWORD = {"table": "TABLE", "view": "VIEW", "materialized view": "MATERIALIZED VIEW"}


def _column(col: ColumnInfo, detail: Detail) -> tuple[str, str]:
    """``(code, note)`` for one column; the note becomes a trailing SQL comment."""
    code = f"  {col.name} {col.type}{'' if col.nullable else ' NOT NULL'}"
    notes = []
    if detail != "columns_only" and col.comment:
        notes.append(col.comment)
    if detail == "full" and col.examples and col.type not in _NO_SAMPLE_TYPES:
        notes.append("e.g. " + ", ".join(repr(v) for v in col.examples))
    return code, " ".join(notes)


def render_relation(info: RelationInfo, detail: Detail, included: set[str]) -> str:
    """DDL-like text for one relation. Joins are shown only towards ``included`` relations."""
    entries = [_column(col, detail) for col in info.columns]
    join_hints = []
    for fk in info.foreign_keys:
        if fk.ref_relation not in included:
            continue  # never point the model at a relation it cannot see
        cols, ref_cols = ", ".join(fk.columns), ", ".join(fk.ref_columns)
        if fk.inferred:  # views have no constraints: say how to join instead
            join_hints.append(f"  -- joins {fk.ref_relation} ({ref_cols}) on ({cols})")
        else:
            entries.append(
                (f"  FOREIGN KEY ({cols}) REFERENCES {fk.ref_relation} ({ref_cols})", "")
            )
    body = [
        code + ("," if i < len(entries) - 1 else "") + (f" -- {note}" if note else "")
        for i, (code, note) in enumerate(entries)
    ]
    header = [f"-- {info.comment}"] if info.comment else []
    keyword = _KEYWORD.get(info.kind, "TABLE")
    return "\n".join([*header, f"CREATE {keyword} {info.name} (", *body, *join_hints, ");"])


def render_within_budget(
    relations: Sequence[RelationInfo], budget: int, count_tokens: TokenCounter
) -> tuple[str, list[Detail], int]:
    """Render ``relations`` (most relevant first) in at most ``budget`` tokens.

    Detail is reduced in stages, least relevant relation first within each stage: drop sample
    values, then column comments, then whole relations. The most relevant relation is never
    dropped, so the result can exceed the budget only if that one alone does.

    Returns:
        The text, the detail level used per relation, and its token count.
    """
    details: list[Detail] = ["full"] * len(relations)

    def render() -> tuple[str, int]:
        included = {r.name for r, d in zip(relations, details, strict=True) if d != "dropped"}
        text = "\n\n".join(
            render_relation(r, d, included)
            for r, d in zip(relations, details, strict=True)
            if d != "dropped"
        )
        return text, count_tokens(text)

    text, tokens = render()
    stages: list[tuple[Detail, range]] = [
        ("no_examples", range(len(relations) - 1, -1, -1)),
        ("columns_only", range(len(relations) - 1, -1, -1)),
        ("dropped", range(len(relations) - 1, 0, -1)),  # never the first
    ]
    for level, order in stages:
        for i in order:
            if tokens <= budget:
                return text, details, tokens
            details[i] = level
            text, tokens = render()
    return text, details, tokens
