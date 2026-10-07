from text2sql.retrieval.catalog import MAX_VALUE_CHARS, _shorten

# Introspection itself runs against Postgres: see tests/integration/test_catalog.py.


def test_shorten_collapses_whitespace_and_truncates() -> None:
    assert _shorten("a\n  b") == "a b"
    long = _shorten("x" * 200)
    assert len(long) == MAX_VALUE_CHARS
    assert long.endswith("…")
