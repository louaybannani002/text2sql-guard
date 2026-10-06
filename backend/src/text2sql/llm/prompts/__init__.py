"""Versioned prompt files, loaded by name.

A prompt ``<name>`` is the pair ``<name>.system.md`` (static instructions) and
``<name>.user.md`` (a ``string.Template`` with ``$placeholders``). Never edit a released
version in place: copy it to ``<name-without-version>_v<N+1>`` so behaviour changes are
explicit in code and visible in git diffs.
"""

import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from string import Template

_NAME = re.compile(r"^[a-z][a-z0-9_]*_v[0-9]+$")


class PromptNotFoundError(LookupError):
    """No prompt files exist for the requested name."""


@dataclass(frozen=True, slots=True)
class Prompt:
    """A loaded prompt version."""

    name: str
    system: str
    user_template: Template

    def render_user(self, **values: str) -> str:
        """Fill the user template. Every placeholder must be given; values are not re-parsed."""
        return self.user_template.substitute(values)


@cache
def load_prompt(name: str) -> Prompt:
    """Load prompt ``name`` (e.g. ``"generate_v1"``) from this package."""
    if not _NAME.match(name):
        msg = f"invalid prompt name {name!r}; expected e.g. 'generate_v1'"
        raise ValueError(msg)
    folder = files(__package__)
    system, user = folder / f"{name}.system.md", folder / f"{name}.user.md"
    if not (system.is_file() and user.is_file()):
        msg = f"prompt {name!r} not found (need {name}.system.md and {name}.user.md)"
        raise PromptNotFoundError(msg)
    return Prompt(
        name=name,
        system=system.read_text(encoding="utf-8").strip(),
        user_template=Template(user.read_text(encoding="utf-8").strip()),
    )
