"""Cache keys: normalised questions and the scope that invalidates entries automatically.

Every key embeds the catalog's ``schema_version``, the generation prompt version and the model
(plus the embedding model for vectors), so changing any of them starts a fresh namespace; old
entries are never read again and expire through their TTL. Keys hold hashes, never question text.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

KEY_FORMAT = "v1"  # bump when the stored entry format changes
PREFIX = "t2s:cache"

_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?!.]+$")
# Numbers and quoted strings: the parts of a question two near-identical embeddings disagree on.
_LITERALS = re.compile(r"\d+(?:[.,]\d+)*|'[^']*'|\"[^\"]*\"")


def normalize_question(question: str) -> str:
    """NFKC, case-folded, whitespace collapsed, trailing ``?!.`` dropped."""
    text = unicodedata.normalize("NFKC", question).casefold()
    return _TRAILING.sub("", _SPACES.sub(" ", text).strip())


def literal_fingerprint(question: str) -> str:
    """Hash of the numbers and quoted strings in the question, in order.

    A semantic hit also needs equal fingerprints: "orders in 2017" and "orders in 2018" embed
    almost identically but need different SQL.
    """
    literals = _LITERALS.findall(normalize_question(question))
    return _digest(literals)[:16]


def _digest(parts: list[str]) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheScope:
    """What a cached SQL query depends on besides the question."""

    schema_version: str
    prompt_version: str
    model: str
    embedding_model: str

    def exact_key(self, question: str) -> str:
        """Key of the exact entry for ``question`` (validated SQL and its result)."""
        parts = [
            KEY_FORMAT,
            normalize_question(question),
            self.schema_version,
            self.prompt_version,
            self.model,
        ]
        return f"{PREFIX}:exact:{_digest(parts)}"

    def semantic_namespace(self) -> str:
        """Prefix of every semantic-cache key in this scope."""
        parts = [
            KEY_FORMAT,
            self.schema_version,
            self.prompt_version,
            self.model,
            self.embedding_model,
        ]
        return f"{PREFIX}:semantic:{_digest(parts)[:32]}"
