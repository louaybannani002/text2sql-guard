from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from text2sql.retrieval.examples import Example, ExampleFileError, load_examples

SEED_FILE = Path(__file__).parents[2] / "db" / "seeds" / "examples.toml"
SEEDS = load_examples(SEED_FILE)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "examples.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_and_normalises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[example]]\nid = "a"\nquestion = "  How   many? "\nsql = """\nSELECT 1;\n"""\n',
    )
    assert load_examples(path) == [Example("a", "How many?", "SELECT 1")]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ('[[example]]\nid = "a"\nquestion = "q"\n', "exactly id, question, sql"),
        ('[[example]]\nid = "A-1"\nquestion = "q"\nsql = "s"\n', "snake_case"),
        ('[[example]]\nid = "a"\nquestion = ""\nsql = "s"\n', "empty"),
        (
            (
                '[[example]]\nid = "a"\nquestion = "q"\nsql = "s"\n'
                '[[example]]\nid = "a"\nquestion = "q2"\nsql = "s2"\n'
            ),
            "duplicate",
        ),
        ("not toml [", "invalid TOML"),
    ],
)
def test_rejects_malformed_files(tmp_path: Path, body: str, error: str) -> None:
    with pytest.raises(ExampleFileError, match=error):
        load_examples(_write(tmp_path, body))


def test_content_hash_tracks_question_and_sql() -> None:
    base = Example("a", "q", "SELECT 1")
    assert base.content_hash != Example("a", "q2", "SELECT 1").content_hash
    assert base.content_hash != Example("a", "q", "SELECT 2").content_hash


# ---------------------------------------------------------------- the reviewed seed file


def test_seed_file_has_twenty_examples() -> None:
    assert len(SEEDS) == 20


@pytest.mark.parametrize("example", SEEDS, ids=lambda e: e.example_id)
def test_seed_sql_follows_generation_rules(example: Example) -> None:
    statements = sqlglot.parse(example.sql, read="postgres")
    assert len(statements) == 1
    tree = statements[0]
    assert isinstance(tree, exp.Query), "must be a single SELECT (CTEs allowed)"

    stars = [s for s in tree.find_all(exp.Star) if not isinstance(s.parent, exp.Count)]
    assert stars == [], "no SELECT * / alias.*"

    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        assert table.name in ctes or table.db == "shop", f"unqualified table {table.name}"
        assert table.alias, f"table {table.name} has no alias"

    output_aliases = {a.alias for a in tree.find_all(exp.Alias)}
    for column in tree.find_all(exp.Column):
        # Unqualified names are only allowed when they refer to an output alias.
        assert column.table or column.name in output_aliases, f"unqualified column {column.name}"

    assert not list(tree.find_all(exp.Join)) or all(
        join.args.get("on") is not None for join in tree.find_all(exp.Join)
    ), "explicit JOIN ... ON only"
