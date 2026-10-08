"""JWT access tokens (HS256, short-lived) and the demo user.

Tokens carry ``sub``, ``iss``, ``aud``, ``iat``, ``exp`` and a unique ``jti``; nothing is stored
server-side, so any API instance can verify any token (stateless).
"""

import hmac
import time
import uuid
from dataclasses import dataclass

import jwt
from pydantic import SecretStr

ALGORITHM = "HS256"
ISSUER = "text2sql-guard"
AUDIENCE = "text2sql-guard-api"
_LEEWAY_S = 5  # clock skew between instances


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller."""

    user_id: str
    token_id: str


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly signed access token."""

    access_token: str
    expires_in: int


class InvalidTokenError(Exception):
    """The token is missing, malformed, expired, or not ours. Deliberately unspecific."""


def issue_token(
    user_id: str, secret: SecretStr, ttl_s: int, *, now: float | None = None
) -> IssuedToken:
    """Sign an access token for ``user_id`` valid for ``ttl_s`` seconds."""
    issued_at = int(now if now is not None else time.time())
    claims = {
        "sub": user_id,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + ttl_s,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, secret.get_secret_value(), algorithm=ALGORITHM)
    return IssuedToken(access_token=token, expires_in=ttl_s)


def verify_token(token: str, secret: SecretStr) -> Principal:
    """Check signature, algorithm, issuer, audience and expiry; return the caller."""
    try:
        claims = jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=[ALGORITHM],  # never trust the token's own "alg" header
            audience=AUDIENCE,
            issuer=ISSUER,
            leeway=_LEEWAY_S,
            options={"require": ["sub", "exp", "iat", "jti"]},
        )
    except jwt.PyJWTError as exc:
        msg = "invalid token"
        raise InvalidTokenError(msg) from exc
    return Principal(user_id=str(claims["sub"]), token_id=str(claims["jti"]))


def check_demo_credentials(
    username: str, password: str, expected_user: str, expected_password: SecretStr
) -> bool:
    """Constant-time comparison of both fields (no early exit on the username)."""
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode())
    password_ok = hmac.compare_digest(
        password.encode(), expected_password.get_secret_value().encode()
    )
    return user_ok and password_ok
