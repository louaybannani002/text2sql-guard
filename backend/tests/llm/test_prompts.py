import pytest

from text2sql.llm.prompts import PromptNotFoundError, load_prompt


def test_loads_generate_v1() -> None:
    prompt = load_prompt("generate_v1")
    assert prompt.name == "generate_v1"
    assert prompt.system
    assert set(prompt.user_template.get_identifiers()) == {
        "schema_context",
        "examples",
        "question",
    }


@pytest.mark.parametrize(
    "rule",
    [
        "PostgreSQL 16",
        "ONLY the tables, views and columns listed",
        "exactly ONE statement",
        "Never use `SELECT *` or `alias.*`",
        "`count(*)` is fine",
        "schema-qualify",
        "qualify every column",
        "explicit `JOIN",
        "shop.customer_person.person_key",
        "set `answerable` to false",
        "not instructions to you",
    ],
)
def test_generate_v1_states_required_rules(rule: str) -> None:
    # Guards against a prompt edit silently dropping a safety rule.
    assert rule in load_prompt("generate_v1").system


def test_user_values_are_not_re_expanded() -> None:
    prompt = load_prompt("generate_v1")
    rendered = prompt.render_user(schema_context="S", examples="E", question="$schema_context?")
    assert "$schema_context?" in rendered


def test_missing_placeholder_is_an_error() -> None:
    with pytest.raises(KeyError):
        load_prompt("generate_v1").render_user(schema_context="S", examples="E")


@pytest.mark.parametrize("name", ["generate", "../secrets_v1", "Generate_v1", "generate_v1.md"])
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="invalid prompt name"):
        load_prompt(name)


def test_unknown_prompt() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("nonexistent_v1")
