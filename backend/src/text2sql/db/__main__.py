"""Database CLI: ``python -m text2sql.db <command>``, run from ``backend/``."""

import argparse
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from text2sql.config.settings import Settings, get_settings
from text2sql.db.connection import connect
from text2sql.db.migrations import migrate
from text2sql.db.olist.loader import load_all
from text2sql.db.roles import APP_ROLE, READER_ROLE, sync_login_passwords
from text2sql.db.views import refresh_materialized_views
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.observability.logging import configure_logging, get_logger
from text2sql.retrieval.build import build_catalog
from text2sql.retrieval.examples import load_examples

log = get_logger(__name__)


async def _migrate(settings: Settings) -> None:
    conn = await connect(settings.database_url)
    try:
        await migrate(conn, settings.migrations_dir)
        await sync_login_passwords(
            conn,
            {READER_ROLE: settings.reader_database_url, APP_ROLE: settings.app_database_url},
        )
    finally:
        await conn.close()


async def _load_olist(settings: Settings) -> None:
    conn = await connect(settings.database_url)
    try:
        counts = await load_all(conn, settings.raw_data_dir)
    finally:
        await conn.close()
    log.info("olist_loaded", total_rows=sum(counts.values()), **counts)


async def _refresh_views(settings: Settings) -> None:
    conn = await connect(settings.database_url)
    try:
        await refresh_materialized_views(conn)
    finally:
        await conn.close()


async def _catalog(settings: Settings, *, force: bool) -> None:
    config = LLMConfig.from_settings(settings)
    examples = load_examples(settings.examples_seed_path)
    conn = await connect(settings.database_url)
    try:
        await build_catalog(
            conn,
            examples=examples,
            embed=lambda texts: embed_texts(texts, config=config),
            embedding_model=config.embedding_model,
            force=force,
        )
    finally:
        await conn.close()


COMMANDS: dict[str, Callable[[Settings], Coroutine[Any, Any, None]]] = {
    "migrate": _migrate,
    "load-olist": _load_olist,
    "refresh-views": _refresh_views,
    "catalog": lambda settings: _catalog(settings, force=False),
    "catalog-force": lambda settings: _catalog(settings, force=True),
}


def main() -> None:
    """Parse arguments and run the chosen command."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.db")
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "development")
    asyncio.run(COMMANDS[args.command](settings))


if __name__ == "__main__":
    main()
