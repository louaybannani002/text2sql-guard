"""The labelled input-guard cases from eval/guard/input_cases.toml."""

import tomllib
from pathlib import Path

_CASES = tomllib.loads(
    (Path(__file__).parents[3] / "eval" / "guard" / "input_cases.toml").read_text(encoding="utf-8")
)

BENIGN: list[str] = [case["text"] for case in _CASES["benign"]]
ATTACKS: list[str] = [case["text"] for case in _CASES["attack"]]
RULE_ATTACKS: list[str] = [case["text"] for case in _CASES["attack"] if case["layer"] == 1]
CLASSIFIER_ATTACKS: list[str] = [case["text"] for case in _CASES["attack"] if case["layer"] == 2]


def case_id(text: str) -> str:
    """Short, ASCII-only test id."""
    return text[:40].encode("ascii", "replace").decode()
