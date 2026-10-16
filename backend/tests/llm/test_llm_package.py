import importlib


def test_package_is_importable() -> None:
    module = importlib.import_module("text2sql.llm")
    assert module.__doc__


def test_litellm_never_loads_the_env_file() -> None:
    import os  # noqa: PLC0415

    from text2sql.llm import _litellm  # noqa: PLC0415, F401 - importing it is the test

    # DEV mode would copy backend/.env (API keys included) into os.environ on import.
    assert os.environ["LITELLM_MODE"] == "PRODUCTION"
