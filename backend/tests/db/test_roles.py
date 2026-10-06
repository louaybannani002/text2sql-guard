import pytest
from pydantic import SecretStr

from text2sql.db.roles import login_password


def test_extracts_and_decodes_password() -> None:
    url = SecretStr("postgresql+asyncpg://t2s_reader:p%40ss@localhost:5432/db")
    assert login_password("t2s_reader", url) == "p@ss"


def test_rejects_url_for_another_user() -> None:
    url = SecretStr("postgresql://admin:pw@localhost/db")
    with pytest.raises(ValueError, match="must log in as t2s_reader"):
        login_password("t2s_reader", url)


def test_rejects_missing_password_without_leaking_url() -> None:
    url = SecretStr("postgresql://t2s_reader@secret-host.internal/db")
    with pytest.raises(ValueError, match="has no password") as exc:
        login_password("t2s_reader", url)
    assert "secret-host" not in str(exc.value)
