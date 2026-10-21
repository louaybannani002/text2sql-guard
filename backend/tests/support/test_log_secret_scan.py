from pathlib import Path

import pytest

from tests.support import log_secret_scan
from tests.support.log_secret_scan import find_secrets

pytest_plugins = ["pytester"]

LEAKY_TEST = """
def test_leaks():
    print("issued eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.abcdefghijkl")
"""


def test_a_passing_test_that_logs_a_secret_fails_the_session(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(secret_scan=Path(log_secret_scan.__file__).read_text(encoding="utf-8"))
    pytester.makeconftest(
        "from secret_scan import SecretScanner\n"
        "def pytest_configure(config):\n"
        "    config.pluginmanager.register(SecretScanner([]), 'scan')\n"
    )
    pytester.makepyfile(test_leaky=LEAKY_TEST)
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*SECRETS FOUND IN TEST OUTPUT*", "jwt: *test_leaks*"])
    assert "abcdefghijkl" not in result.stdout.str().split("SECRETS FOUND")[1]


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("key=sk-proj-" + "a1B2" * 10, "openai_key"),
        ("groq gsk_" + "A1b2" * 12, "groq_key"),
        ("AIza" + "x" * 35, "google_key"),
        ("pk-lf-12345678-1234-1234-1234-123456789abc", "langfuse_key"),
        ("ghp_" + "Z" * 36, "github_token"),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.abcdefghijkl", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ("postgresql://t2s_reader:s3cr3t-pass@db/x", "url_password"),
    ],
)
def test_real_secret_formats_are_found(text: str, name: str) -> None:
    assert name in find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "llm_call model=gemini/x total_tokens=120 cost_usd=0.0",
        "postgresql+asyncpg://t2s_reader:pw@localhost:5432/test",  # tests' 2-char fake password
        "redis://:[redacted]@redis:6379/0",
        "sk-test",  # too short to be a key
    ],
)
def test_ordinary_log_lines_are_clean(text: str) -> None:
    assert find_secrets(text) == []


def test_exact_values_are_found_by_index_not_by_value() -> None:
    hits = find_secrets("demo password: demo-password-for-tests", ["x-not-here", "demo-password"])
    assert hits == ["literal:1"]
