import dataclasses

import pytest

from text2sql.cache.keys import CacheScope, literal_fingerprint, normalize_question

SCOPE = CacheScope(
    schema_version="schema-a",
    prompt_version="generate_v2",
    model="openai/gpt-5.4",
    embedding_model="openai/text-embedding-3-small",
)


@pytest.mark.parametrize(
    "variant",
    [
        "How many orders per status?",
        "how many orders per status",
        "  HOW   many orders\tper status ?! ",
        "How many orders per status.",
        chr(0xFF28) + "ow many orders per status?",  # full-width H, NFKC-normalised
    ],
)
def test_equivalent_questions_share_the_exact_key(variant: str) -> None:
    assert normalize_question(variant) == "how many orders per status"
    assert SCOPE.exact_key(variant) == SCOPE.exact_key("How many orders per status?")


def test_different_questions_have_different_keys() -> None:
    assert SCOPE.exact_key("orders per status") != SCOPE.exact_key("orders per state")


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "schema-b"},
        {"prompt_version": "generate_v3"},
        {"model": "openai/gpt-5.5"},
    ],
)
def test_scope_changes_invalidate_both_levels(change: dict[str, str]) -> None:
    other = dataclasses.replace(SCOPE, **change)
    assert other.exact_key("q") != SCOPE.exact_key("q")
    assert other.semantic_namespace() != SCOPE.semantic_namespace()


def test_embedding_model_only_matters_for_vectors() -> None:
    other = dataclasses.replace(SCOPE, embedding_model="openai/text-embedding-3-large")
    assert other.exact_key("q") == SCOPE.exact_key("q")
    assert other.semantic_namespace() != SCOPE.semantic_namespace()


def test_keys_never_contain_the_question() -> None:
    key = SCOPE.exact_key("revenue of seller acme")
    assert key.startswith("t2s:cache:exact:")
    assert "acme" not in key
    assert "acme" not in SCOPE.semantic_namespace()


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Orders in 2017?", "How many orders were placed in 2017", True),
        ("Orders in 2017?", "Orders in 2018?", False),
        ("Top 5 sellers", "Top 10 sellers", False),
        ("Orders in state 'SP'", "Orders in state 'RJ'", False),
        ("Revenue per month", "Monthly revenue", True),  # no literals at all
        ("Price above 99.90", "Price above 99,90", False),
    ],
)
def test_literal_fingerprint(a: str, b: str, *, same: bool) -> None:
    assert (literal_fingerprint(a) == literal_fingerprint(b)) is same
