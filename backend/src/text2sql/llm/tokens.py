"""Offline token counting for prompt budgets.

Uses tiktoken's ``o200k_base`` (the GPT-4o / GPT-5 tokenizer) from a project-local cache that
``make install`` fills once (``python -m text2sql.llm.tokens``). Counting never touches the
network: without the cached file it falls back to a conservative character estimate, which
over-counts, so a budget is never exceeded because of the fallback.

LiteLLM's bundled copy is not used: its ``token_counter`` loads ``cl100k_base`` (downloaded on
first use) and its bundled ``o200k`` file fails tiktoken's hash check on Windows (CRLF).
"""

import hashlib
import math
import os
import sys
from functools import cache
from pathlib import Path

import tiktoken

from text2sql.observability.logging import get_logger

log = get_logger(__name__)

ENCODING = "o200k_base"
_BLOB_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
_CHARS_PER_TOKEN_ESTIMATE = 3.0  # real ratio is ~4 for English/SQL; lower = safer budget
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache" / "tiktoken"


def _cache_file(cache_dir: Path) -> Path:
    # tiktoken names cache entries by the SHA-1 of the source URL.
    return cache_dir / hashlib.sha1(_BLOB_URL.encode()).hexdigest()  # noqa: S324 - cache key


@cache
def _encoding(cache_dir: Path) -> tiktoken.Encoding | None:
    if not _cache_file(cache_dir).is_file():
        log.warning("tokenizer_cache_missing", encoding=ENCODING, fallback="char_estimate")
        return None
    os.environ["TIKTOKEN_CACHE_DIR"] = str(cache_dir)
    return tiktoken.get_encoding(ENCODING)


def count_tokens(text: str, *, cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    """Number of tokens in ``text`` (exact with the cached tokenizer, else a safe estimate)."""
    encoding = _encoding(cache_dir)
    if encoding is None:
        return math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE)
    return len(encoding.encode(text, disallowed_special=()))


def download(cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Fetch the tokenizer into ``cache_dir`` (network); verified by tiktoken's hash check."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(cache_dir)
    tiktoken.get_encoding(ENCODING)  # downloads, checks the SHA-256, writes the cache file
    _encoding.cache_clear()
    return _cache_file(cache_dir)


if __name__ == "__main__":
    path = download()
    sys.stdout.write(f"{ENCODING} tokenizer cached at {path}\n")
