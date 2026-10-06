"""Database roles created by migration 0004, and helpers to act as / configure them."""

import re
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

import asyncpg
from pydantic import SecretStr

from text2sql.observability.logging import get_logger

log = get_logger(__name__)

OWNER_ROLE = "t2s_owner"
READER_ROLE = "t2s_reader"
APP_ROLE = "t2s_app"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


async def role_exists(conn: asyncpg.Connection, role: str) -> bool:
    """Whether ``role`` exists in the cluster."""
    return bool(
        await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", role)
    )


async def set_local_role(conn: asyncpg.Connection, role: str) -> bool:
    """``SET LOCAL ROLE`` for the current transaction if the role exists.

    Returns:
        True if the role was assumed, False if it does not exist (yet).
    """
    if not _IDENTIFIER.match(role):
        msg = f"invalid role name {role!r}"
        raise ValueError(msg)
    if not await role_exists(conn, role):
        return False
    await conn.execute(f"SET LOCAL ROLE {role}")
    return True


def login_password(role: str, database_url: SecretStr) -> str:
    """Extract the password for ``role`` from a connection URL that logs in as that role."""
    parts = urlsplit(database_url.get_secret_value())
    if parts.username != role:
        msg = f"connection URL for {role} must log in as {role}, not {parts.username!r}"
        raise ValueError(msg)
    if not parts.password:
        msg = f"connection URL for {role} has no password"
        raise ValueError(msg)
    return unquote(parts.password)


async def sync_login_passwords(conn: asyncpg.Connection, urls: Mapping[str, SecretStr]) -> None:
    """Set each role's password to the one in its connection URL (needs a privileged conn)."""
    for role, url in urls.items():
        password = login_password(role, url)
        # ALTER ROLE takes no bind parameters; format() quotes both parts server-side.
        statement = await conn.fetchval(
            "SELECT format('ALTER ROLE %I WITH PASSWORD %L', $1::text, $2::text)", role, password
        )
        await conn.execute(statement)
        log.info("role_password_synced", role=role)
