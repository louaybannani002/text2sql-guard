"""Few-shot examples: hand-reviewed question/SQL pairs kept in a TOML seed file."""

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"^[a-z0-9_]+$")


class ExampleFileError(ValueError):
    """The seed file is malformed."""


@dataclass(frozen=True, slots=True)
class Example:
    """One question with the SQL that answers it."""

    example_id: str
    question: str
    sql: str

    @property
    def content_hash(self) -> str:
        """Changes when the question or the SQL changes."""
        return hashlib.sha256(f"{self.question}\x00{self.sql}".encode()).hexdigest()


def load_examples(path: Path) -> list[Example]:
    """Parse and validate ``[[example]]`` tables (id, question, sql) from ``path``."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path.name}: invalid TOML: {exc}"
        raise ExampleFileError(msg) from exc
    examples: list[Example] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("example", []), start=1):
        if set(raw) != {"id", "question", "sql"}:
            msg = f"{path.name}: example #{i} must have exactly id, question, sql"
            raise ExampleFileError(msg)
        example = Example(
            example_id=str(raw["id"]).strip(),
            question=" ".join(str(raw["question"]).split()),
            sql=str(raw["sql"]).strip().rstrip(";").strip(),
        )
        if not _ID.match(example.example_id):
            msg = f"{path.name}: example #{i} id {example.example_id!r} must be snake_case"
            raise ExampleFileError(msg)
        if example.example_id in seen:
            msg = f"{path.name}: duplicate example id {example.example_id!r}"
            raise ExampleFileError(msg)
        if not example.question or not example.sql:
            msg = f"{path.name}: example {example.example_id!r} has an empty question or sql"
            raise ExampleFileError(msg)
        seen.add(example.example_id)
        examples.append(example)
    return examples
