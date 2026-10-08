"""Postgres access for the API (``t2s_app``): query log, feedback, and the schema summary."""

import uuid
from dataclasses import dataclass

import asyncpg

from text2sql.pipeline.answer import Answer
from text2sql.retrieval.documents import relation_from_definition


@dataclass(frozen=True, slots=True)
class ColumnSummary:
    """A column the query role can read (no sample values: this goes to any client)."""

    name: str
    type: str
    description: str


@dataclass(frozen=True, slots=True)
class TableSummary:
    """A relation users can ask about."""

    name: str
    kind: str
    description: str
    columns: list[ColumnSummary]


class PgStore:
    """The API's tables in schema ``app``."""

    def __init__(self, pool: asyncpg.Pool | asyncpg.Connection) -> None:
        """Use a pool (or, in tests, one connection) logged in as ``t2s_app``."""
        self._pool = pool

    async def record_query(
        self, query_id: uuid.UUID, user_id: str, question: str, answer: Answer | None
    ) -> None:
        """Log one /v1/query call (``answer`` None: it crashed before producing one)."""
        trace = answer.trace if answer else None
        result = answer.result if answer else None
        await self._pool.execute(
            """
            INSERT INTO app.queries (query_id, user_id, question, status, sql, attempts,
                                     row_count, total_ms, total_tokens, cost_usd)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            query_id,
            user_id,
            question,
            answer.status if answer else "error",
            answer.sql if answer else None,
            answer.attempts if answer else 0,
            result.row_count if result else None,
            trace.total_ms if trace else None,
            trace.total_tokens if trace else None,
            trace.total_cost_usd if trace else None,
        )

    async def query_owner(self, query_id: uuid.UUID) -> str | None:
        """Who asked ``query_id`` (None if it does not exist)."""
        owner = await self._pool.fetchval(
            "SELECT user_id FROM app.queries WHERE query_id = $1", query_id
        )
        return str(owner) if owner is not None else None

    async def save_feedback(
        self, query_id: uuid.UUID, user_id: str, rating: int, comment: str | None
    ) -> int:
        """Insert or replace the caller's rating for ``query_id``; returns the feedback id."""
        feedback_id = await self._pool.fetchval(
            """
            INSERT INTO app.feedback (query_id, user_id, rating, comment)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (query_id, user_id)
            DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now()
            RETURNING feedback_id
            """,
            query_id,
            user_id,
            rating,
            comment,
        )
        return int(feedback_id)

    async def schema_summary(self) -> list[TableSummary]:
        """Readable relations and columns from the retrieval catalog."""
        rows = await self._pool.fetch(
            "SELECT definition::text AS definition FROM app.schema_docs ORDER BY relation"
        )
        tables = []
        for row in rows:
            info = relation_from_definition(row["definition"])
            tables.append(
                TableSummary(
                    name=info.name,
                    kind=info.kind,
                    description=info.comment,
                    columns=[ColumnSummary(c.name, c.type, c.comment) for c in info.columns],
                )
            )
        return tables

    async def ping(self) -> None:
        """Raise if the database cannot answer."""
        await self._pool.fetchval("SELECT 1")
