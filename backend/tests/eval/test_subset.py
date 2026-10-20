import pytest

from tests.eval.test_datasets import GOLD
from text2sql.eval.subset import PER_DIFFICULTY, load_subset_ids, stratified_ids


def test_the_stored_subset_follows_the_rule() -> None:
    # Regenerate with stratified_ids, never edit by hand: the subset must not be hand-picked.
    assert load_subset_ids() == stratified_ids(GOLD)


def test_proportions_match_the_full_set() -> None:
    ids = set(load_subset_ids())
    for difficulty, n in PER_DIFFICULTY.items():
        assert sum(g.id in ids and g.difficulty == difficulty for g in GOLD) == n


def test_selection_ignores_dataset_order() -> None:
    assert sorted(stratified_ids(list(reversed(GOLD)))) == sorted(stratified_ids(GOLD))


def test_too_few_questions_is_an_error() -> None:
    with pytest.raises(ValueError, match="only"):
        stratified_ids(GOLD[:3])
