import dataclasses
from pathlib import Path

import pytest

from tests.eval.test_report import _result
from text2sql.config.settings import Settings
from text2sql.eval import cli


def test_parse_args_defaults() -> None:
    args = cli.parse_args([])
    assert (args.model, args.smoke, args.concurrency, args.no_cache) == ("main", False, 2, False)
    assert args.datasets == ["gold", "adversarial", "benign"]
    assert args.out_dir == cli.DEFAULT_OUT


def test_skipped_run_explains_why(settings: Settings) -> None:
    result = cli.skipped(settings, "local", "server down", smoke=False)
    assert result.info.model == settings.llm_model_local
    assert result.metrics.notes == ["skipped: server down"]


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> list[str]:
    calls: list[str] = []

    async def fake_evaluate(_settings: Settings, choice: str, **_kwargs: object) -> object:
        calls.append(choice)
        return _result(smoke=True, choice=choice)

    async def unreachable(_base: object) -> bool:
        return False

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli, "local_model_reachable", unreachable)
    return calls


async def test_smoke_exit_code_follows_the_thresholds(patched: list[str], tmp_path: Path) -> None:
    # The fake run has 50% accuracy: below the 75% smoke threshold.
    code = await cli._main(cli.parse_args(["--smoke", "--out-dir", str(tmp_path)]))  # noqa: SLF001
    assert (patched, code) == (["main"], 1)
    assert (tmp_path / "2026-10-09_openai-gpt-5.4_smoke.md").exists()


async def test_both_models_write_a_comparison_even_when_local_is_down(
    patched: list[str], tmp_path: Path
) -> None:
    code = await cli._main(cli.parse_args(["--model", "both", "--out-dir", str(tmp_path)]))  # noqa: SLF001
    assert (patched, code) == (["main"], 0)
    comparison = (tmp_path / "2026-10-09_main-vs-local.md").read_text(encoding="utf-8")
    assert "main vs local" in comparison


async def test_local_only_and_unreachable_is_an_error(patched: list[str], tmp_path: Path) -> None:
    code = await cli._main(cli.parse_args(["--model", "local", "--out-dir", str(tmp_path)]))  # noqa: SLF001
    assert (patched, code) == ([], 2)


async def test_a_dead_provider_aborts_with_exit_code_3(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def provider_down(_settings: Settings, choice: str, **_kwargs: object) -> object:
        result = _result(choice=choice)
        metrics = dataclasses.replace(result.metrics, notes=[cli.PROVIDER_DOWN])
        return dataclasses.replace(result, metrics=metrics)

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "evaluate", provider_down)
    code = await cli._main(cli.parse_args(["--out-dir", str(tmp_path)]))  # noqa: SLF001
    assert code == 3
