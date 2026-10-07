import math
from pathlib import Path

import pytest

from text2sql.llm import tokens
from text2sql.llm.tokens import DEFAULT_CACHE_DIR, count_tokens


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    tokens._encoding.cache_clear()  # noqa: SLF001 - reset the per-directory memo between tests


def test_falls_back_to_a_conservative_estimate_without_cache(tmp_path: Path) -> None:
    text = "SELECT count(*) FROM shop.orders AS o"
    assert count_tokens(text, cache_dir=tmp_path) == math.ceil(len(text) / 3.0)
    assert count_tokens("", cache_dir=tmp_path) == 0


@pytest.mark.skipif(
    not any(DEFAULT_CACHE_DIR.glob("*")), reason="tokenizer not cached; run `make install`"
)
def test_exact_count_with_cached_tokenizer() -> None:
    text = "CREATE TABLE shop.orders (order_id shop.olist_id NOT NULL) -- comment"
    exact = count_tokens(text)
    assert 10 <= exact <= 25
    # The fallback must never under-count compared to the real tokenizer.
    assert math.ceil(len(text) / 3.0) >= exact


def test_special_token_text_does_not_raise(tmp_path: Path) -> None:
    # User text may contain strings that look like special tokens.
    assert count_tokens("<|endoftext|>", cache_dir=tmp_path) > 0
    if any(DEFAULT_CACHE_DIR.glob("*")):
        assert count_tokens("<|endoftext|>") > 0
