import importlib


def test_package_is_importable() -> None:
    module = importlib.import_module("text2sql.executor")
    assert module.__doc__
