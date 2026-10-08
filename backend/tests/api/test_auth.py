import time

import jwt
import pytest
from pydantic import SecretStr

from text2sql.api.auth import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    InvalidTokenError,
    check_demo_credentials,
    issue_token,
    verify_token,
)

SECRET = SecretStr("unit-test-secret-0123456789-abcdefghij")


def test_round_trip() -> None:
    issued = issue_token("demo", SECRET, 900)
    principal = verify_token(issued.access_token, SECRET)
    assert principal.user_id == "demo"
    assert len(principal.token_id) == 32
    assert issued.expires_in == 900


def test_every_token_is_unique() -> None:
    assert (
        issue_token("demo", SECRET, 900).access_token
        != issue_token("demo", SECRET, 900).access_token
    )


def test_expired_token_is_rejected() -> None:
    old = issue_token("demo", SECRET, 60, now=time.time() - 3600)
    with pytest.raises(InvalidTokenError):
        verify_token(old.access_token, SECRET)


def _forge(
    claims: dict[str, object], key: str = SECRET.get_secret_value(), alg: str = ALGORITHM
) -> str:
    now = int(time.time())
    base: dict[str, object] = {
        "sub": "demo",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 600,
        "jti": "x",
    }
    return jwt.encode(base | claims, key, algorithm=alg)


@pytest.mark.parametrize(
    "token",
    [
        _forge({}, key="another-secret-of-sufficient-length-1234"),  # wrong signature
        _forge({"aud": "someone-else"}),
        _forge({"iss": "someone-else"}),
        _forge({}, key="k" * 64, alg="HS512"),  # algorithm not on the allowlist
        jwt.encode({"sub": "demo"}, None, algorithm="none"),  # unsigned
        "not-a-jwt",
        "",
    ],
    ids=["signature", "audience", "issuer", "algorithm", "alg_none", "garbage", "empty"],
)
def test_forged_or_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        verify_token(token, SECRET)


def test_missing_required_claims_are_rejected() -> None:
    token = jwt.encode(
        {"sub": "demo", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60},
        SECRET.get_secret_value(),
        algorithm=ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):  # no iat / jti
        verify_token(token, SECRET)


@pytest.mark.parametrize(
    ("username", "password", "ok"),
    [
        ("demo", "pw-long-enough", True),
        ("demo", "wrong", False),
        ("other", "pw-long-enough", False),
    ],
)
def test_demo_credentials(username: str, password: str, ok: bool) -> None:  # noqa: FBT001
    assert check_demo_credentials(username, password, "demo", SecretStr("pw-long-enough")) is ok
