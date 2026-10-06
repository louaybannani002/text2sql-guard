"""Refresh of materialized views after data loads."""

import asyncpg

from text2sql.db.roles import OWNER_ROLE, set_local_role
from text2sql.observability.logging import get_logger

log = get_logger(__name__)


async def refresh_materialized_views(conn: asyncpg.Connection, schema: str = "shop") -> list[str]:
    """Refresh every materialized view in ``schema`` as the schema owner, in one transaction.

    Returns:
        Qualified names of the refreshed views.
    """
    async with conn.transaction():
        await set_local_role(conn, OWNER_ROLE)
        names = await conn.fetch(
            "SELECT format('%I.%I', schemaname, matviewname) AS name"
            " FROM pg_matviews WHERE schemaname = $1 ORDER BY matviewname",
            schema,
        )
        refreshed = [row["name"] for row in names]
        for name in refreshed:
            # Names come from pg_matviews and are quoted by format('%I').
            await conn.execute(f"REFRESH MATERIALIZED VIEW {name}")
            log.info("materialized_view_refreshed", view=name)
    return refreshed
