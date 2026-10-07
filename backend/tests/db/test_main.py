import sys

import pytest

from text2sql.config.settings import Settings
from text2sql.db import __main__ as cli


def test_commands() -> None:
    assert sorted(cli.COMMANDS) == [
        "catalog",
        "catalog-force",
        "load-olist",
        "migrate",
        "refresh-views",
    ]


@pytest.mark.parametrize(("command", "force"), [("catalog", False), ("catalog-force", True)])
async def test_catalog_commands_pass_force_flag(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    command: str,
    force: bool,  # noqa: FBT001
) -> None:
    calls: list[bool] = []

    async def fake_catalog(_settings: Settings, *, force: bool) -> None:
        calls.append(force)

    monkeypatch.setattr(cli, "_catalog", fake_catalog)
    await cli.COMMANDS[command](settings)
    assert calls == [force]


def test_main_runs_the_chosen_command(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    ran: list[Settings] = []

    async def fake_refresh(s: Settings) -> None:
        ran.append(s)

    monkeypatch.setattr(sys, "argv", ["python -m text2sql.db", "refresh-views"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setitem(cli.COMMANDS, "refresh-views", fake_refresh)
    cli.main()
    assert ran == [settings]


def test_main_rejects_unknown_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m text2sql.db", "drop-everything"])
    with pytest.raises(SystemExit):
        cli.main()
