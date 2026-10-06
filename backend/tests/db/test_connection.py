import pytest
from pydantic import SecretStr

from text2sql.db.connection import asyncpg_dsn


def test_strips_driver_suffix() -> None:
    assert asyncpg_dsn("postgresql+asyncpg://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"


def test_accepts_secret_and_plain_scheme() -> None:
    assert asyncpg_dsn(SecretStr("postgresql://u:p@h/d")) == "postgresql://u:p@h/d"


def test_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="database URL"):
        asyncpg_dsn("not a url")
