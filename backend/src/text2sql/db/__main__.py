"""Database CLI: ``python -m text2sql.db {migrate,load-olist}`` (run from ``backend/``)."""

import argparse
import asyncio

from text2sql.config.settings import Settings, get_settings
from text2sql.db.connection import connect
from text2sql.db.migrations import migrate
from text2sql.db.olist.loader import load_all
from text2sql.observability.logging import configure_logging, get_logger

log = get_logger(__name__)


async def _migrate(settings: Settings) -> None:
    conn = await connect(settings.database_url)
    try:
        await migrate(conn, settings.migrations_dir)
    finally:
        await conn.close()


async def _load_olist(settings: Settings) -> None:
    conn = await connect(settings.database_url)
    try:
        counts = await load_all(conn, settings.raw_data_dir)
    finally:
        await conn.close()
    log.info("olist_loaded", total_rows=sum(counts.values()), **counts)


def main() -> None:
    """Parse arguments and run the chosen command."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.db")
    parser.add_argument("command", choices=["migrate", "load-olist"])
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "development")
    command = _migrate if args.command == "migrate" else _load_olist
    asyncio.run(command(settings))


if __name__ == "__main__":
    main()
