"""Pytest plugin: scan every test's captured output (stdout, stderr, logs) for secrets.

The whole suite's logs go through ``find_secrets``: real key formats (OpenAI, Groq, Gemini,
Langfuse, GitHub, JWTs, private keys, URLs with passwords) and the exact secret values of the
fake test environment. Any hit fails the run, naming the test and the pattern, never the value.
Logs are supposed to carry ids, counts and statuses only (see CLAUDE.md, conventions 5 and 6).
"""

import re
from collections.abc import Iterable

import pytest

PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "groq_key": re.compile(r"\bgsk_[A-Za-z0-9]{40,}"),
    "google_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "langfuse_key": re.compile(
        r"\b[ps]k-lf-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    ),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "url_password": re.compile(r"\b[a-z][a-z0-9+.-]*://[^:/\s@]+:[^@\s]{8,}@"),
}


def find_secrets(text: str, literals: Iterable[str] = ()) -> list[str]:
    """Names of the patterns (and ``literal:<n>``) found in ``text``; never the values."""
    hits = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    hits += [f"literal:{i}" for i, value in enumerate(literals) if value and value in text]
    return hits


class SecretScanner:
    """Collects hits from every test report; fails the session if there are any."""

    def __init__(self, literals: list[str]) -> None:
        self.literals = literals
        self.hits: list[tuple[str, str, str]] = []  # (test, section, pattern)

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        for section, content in report.sections:
            for name in find_secrets(content, self.literals):
                self.hits.append((report.nodeid, section, name))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if not self.hits:
            return
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "SECRETS FOUND IN TEST OUTPUT", red=True)
            for test, section, name in sorted(set(self.hits)):
                reporter.write_line(f"{name}: {test} ({section})")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
