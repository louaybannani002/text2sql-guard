"""Versioned prompt files, loaded by name.

A prompt ``<name>`` is the pair ``<name>.system.md`` (static instructions) and
``<name>.user.md`` (a ``string.Template`` with ``$placeholders``). Never edit a released
version in place: copy it to ``<name-without-version>_v<N+1>`` so behaviour changes are
explicit in code and visible in git diffs.

A system prompt may include a shared, versioned fragment with a line of its own:
``{{include:glossary_v1}}`` is replaced by the content of ``glossary_v1.md``.
"""

import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from string import Template

_NAME = re.compile(r"^[a-z][a-z0-9_]*_v[0-9]+$")
_INCLUDE = re.compile(r"^\{\{include:([a-z][a-z0-9_]*_v[0-9]+)\}\}$", re.MULTILINE)


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
        system=_expand_includes(system.read_text(encoding="utf-8").strip()),
        user_template=Template(user.read_text(encoding="utf-8").strip()),
    )


def _expand_includes(text: str) -> str:
    folder = files(__package__)

    def fragment(match: re.Match[str]) -> str:
        path = folder / f"{match[1]}.md"
        if not path.is_file():
            msg = f"included prompt fragment {match[1]!r} not found ({match[1]}.md)"
            raise PromptNotFoundError(msg)
        return path.read_text(encoding="utf-8").strip()

    return _INCLUDE.sub(fragment, text)
