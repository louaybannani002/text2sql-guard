"""shop.customer_person: repeat customers are countable without exposing customer_unique_id."""

import asyncpg
import pytest
from asyncpg.exceptions import InsufficientPrivilegeError

from tests.integration.support import expect_failure
from text2sql.db.views import refresh_materialized_views

pytestmark = pytest.mark.integration

REPEAT_CUSTOMERS = """
SELECT count(*) FROM (
    SELECT cp.person_key
    FROM shop.orders o JOIN shop.customer_person cp USING (customer_id)
    GROUP BY cp.person_key
    HAVING count(*) > 1
) repeaters
"""


async def test_reader_can_count_unique_and_repeat_customers(
    reader: asyncpg.Connection, admin: asyncpg.Connection
) -> None:
    # Ground truth from the restricted column, computed as admin.
    truth = await admin.fetchrow(
        "SELECT count(DISTINCT customer_unique_id) AS people,"
        " (SELECT count(*) FROM (SELECT 1 FROM shop.customers GROUP BY customer_unique_id"
        "  HAVING count(*) > 1) r) AS repeaters FROM shop.customers"
    )
    assert truth is not None

    people = await reader.fetchval("SELECT count(DISTINCT person_key) FROM shop.customer_person")
    repeaters = await reader.fetchval(REPEAT_CUSTOMERS)
    assert (people, repeaters) == (truth["people"], truth["repeaters"])
    assert (people, repeaters) == (96_096, 2_997)  # known values of the Olist dataset


async def test_reader_still_cannot_read_customer_unique_id(reader: asyncpg.Connection) -> None:
    await expect_failure(
        reader, "SELECT customer_unique_id FROM shop.customers", InsufficientPrivilegeError
    )


async def test_view_exposes_only_opaque_integer_key(reader: asyncpg.Connection) -> None:
    columns = await reader.fetch(
        "SELECT a.attname, t.typnamespace::regnamespace::text || '.' || t.typname AS type"
        " FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid"
        " WHERE a.attrelid = 'shop.customer_person'::regclass AND a.attnum > 0"
        " AND NOT a.attisdropped ORDER BY a.attnum"
    )
    assert [(c["attname"], c["type"]) for c in columns] == [
        ("customer_id", "shop.olist_id"),
        ("person_key", "pg_catalog.int4"),
    ]


async def test_same_person_gets_same_key(admin: asyncpg.Connection) -> None:
    mismatches = await admin.fetchval(
        "SELECT count(*) FROM ("
        " SELECT c.customer_unique_id FROM shop.customers c"
        " JOIN shop.customer_person cp USING (customer_id)"
        " GROUP BY c.customer_unique_id HAVING count(DISTINCT cp.person_key) <> 1) bad"
    )
    assert mismatches == 0


async def test_refresh_runs_as_owner_and_keeps_counts(admin: asyncpg.Connection) -> None:
    before = await admin.fetchval("SELECT count(*) FROM shop.customer_person")
    assert await refresh_materialized_views(admin) == ["shop.customer_person"]
    assert await admin.fetchval("SELECT count(*) FROM shop.customer_person") == before
