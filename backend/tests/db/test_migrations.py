from pathlib import Path

import pytest

from text2sql.db.migrations import Migration, MigrationError, discover, pending, runs_as_owner

REPO_MIGRATIONS = Path(__file__).parents[2] / "db" / "migrations"


def _write(directory: Path, name: str, sql: str = "SELECT 1;") -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_discover_sorts_by_version(tmp_path: Path) -> None:
    _write(tmp_path, "0002_b.sql")
    _write(tmp_path, "0010_c.sql")
    _write(tmp_path, "0001_a.sql")
    assert [(m.version, m.name) for m in discover(tmp_path)] == [(1, "a"), (2, "b"), (10, "c")]


@pytest.mark.parametrize("name", ["1_short.sql", "0001-dash.sql", "0001_Upper.sql", "0001_.sql"])
def test_discover_rejects_bad_names(tmp_path: Path, name: str) -> None:
    _write(tmp_path, name)
    with pytest.raises(MigrationError, match="bad migration filename"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    _write(tmp_path, "0001_b.sql")
    with pytest.raises(MigrationError, match="duplicate"):
        discover(tmp_path)


def test_checksum_ignores_line_endings() -> None:
    assert Migration(1, "a", "SELECT 1;\r\n").checksum == Migration(1, "a", "SELECT 1;\n").checksum


def test_pending_skips_applied() -> None:
    first, second = Migration(1, "a", "x"), Migration(2, "b", "y")
    assert pending([first, second], {1: first.checksum}) == [second]
    assert pending([first, second], {1: first.checksum, 2: second.checksum}) == []


def test_pending_rejects_modified_migration() -> None:
    with pytest.raises(MigrationError, match="modified"):
        pending([Migration(1, "a", "changed")], {1: Migration(1, "a", "original").checksum})


def test_pending_rejects_missing_file() -> None:
    with pytest.raises(MigrationError, match="missing"):
        pending([], {1: "abc"})


def test_repository_migrations_are_valid() -> None:
    migrations = discover(REPO_MIGRATIONS)
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))


def test_admin_marker_must_be_first_line() -> None:
    assert Migration(4, "roles", "-- migrate: admin\nCREATE ROLE x;").runs_as_admin
    assert Migration(4, "roles", "\n  -- migrate: admin  \nCREATE ROLE x;").runs_as_admin
    assert not Migration(5, "t", "CREATE TABLE t ();\n-- migrate: admin").runs_as_admin
    assert not Migration(5, "t", "-- migrate: administrator").runs_as_admin


def test_runs_as_owner_only_after_bootstrap() -> None:
    migrations = [
        Migration(1, "a", "CREATE TABLE a ();"),
        Migration(2, "roles", "-- migrate: admin\nCREATE ROLE x;"),
        Migration(3, "b", "CREATE TABLE b ();"),
    ]
    assert [runs_as_owner(m, migrations) for m in migrations] == [False, False, True]


def test_without_bootstrap_nothing_runs_as_owner() -> None:
    migrations = [Migration(1, "a", "x"), Migration(2, "b", "y")]
    assert not any(runs_as_owner(m, migrations) for m in migrations)


def test_only_the_role_bootstrap_runs_as_admin() -> None:
    assert [m.version for m in discover(REPO_MIGRATIONS) if m.runs_as_admin] == [4]
