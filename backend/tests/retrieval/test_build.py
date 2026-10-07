from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest

from tests.support.fake_embedder import FAKE_EMBEDDING_MODEL, FakeEmbedder
from text2sql.retrieval.build import CatalogBuildError, _stale, build_catalog
from text2sql.retrieval.store import StoredEntry

if TYPE_CHECKING:
    import asyncpg

# Database behaviour (introspection, diffing, storage) is covered against Postgres in
# tests/integration/test_catalog.py; these tests cover the pure decision logic.


def test_stale_detects_new_changed_and_model_switch() -> None:
    stored = {
        "same": StoredEntry("h1", "m"),
        "changed": StoredEntry("old", "m"),
        "other_model": StoredEntry("h3", "old-model"),
        "removed": StoredEntry("h4", "m"),
    }
    current = {"same": "h1", "changed": "h2", "other_model": "h3", "new": "h5"}
    assert sorted(_stale(current, stored, "m", force=False)) == ["changed", "new", "other_model"]
    assert sorted(_stale(current, stored, "m", force=True)) == sorted(current)


def test_stale_with_nothing_stored_is_everything() -> None:
    assert sorted(_stale({"a": "1", "b": "2"}, {}, "m", force=False)) == ["a", "b"]


class _NoOwnerConnection:
    """Just enough of asyncpg.Connection for build_catalog to discover the owner is missing."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetchval(self, query: str, *args: Any) -> bool:  # noqa: ANN401
        del args
        assert "pg_roles" in query, query
        return False


async def test_missing_owner_role_fails_before_touching_anything() -> None:
    embedder = FakeEmbedder()
    with pytest.raises(CatalogBuildError, match="run the migrations"):
        await build_catalog(
            cast("asyncpg.Connection", _NoOwnerConnection()),
            examples=[],
            embed=embedder,
            embedding_model=FAKE_EMBEDDING_MODEL,
        )
    assert embedder.batches == []
