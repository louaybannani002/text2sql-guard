"""POST /v1/auth/token: exchange the demo user's credentials for a short-lived access token."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from text2sql.api.auth import check_demo_credentials, issue_token
from text2sql.api.dependencies import ServicesDep, rate_limit_headers
from text2sql.api.errors import ApiError
from text2sql.observability.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["auth"])


class TokenRequest(BaseModel):
    """Demo user credentials."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """An OAuth2-style bearer token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a token type, not a secret
    expires_in: int


@router.post("/token", responses={401: {}, 429: {}})
async def token(body: TokenRequest, request: Request, services: ServicesDep) -> TokenResponse:
    """Rate-limited per client address, so passwords cannot be brute-forced."""
    client = request.client.host if request.client else "unknown"
    decision = await services.token_limiter.hit(client)
    if not decision.allowed:
        raise ApiError(
            429, "rate_limited", "Too many login attempts.", headers=rate_limit_headers(decision)
        )
    settings = services.settings
    if not check_demo_credentials(
        body.username, body.password, settings.demo_username, settings.demo_password
    ):
        log.warning("login_failed")  # never log the submitted username or password
        raise ApiError(401, "unauthorized", "Invalid username or password.")
    issued = issue_token(settings.demo_username, settings.jwt_secret, settings.jwt_access_ttl_s)
    log.info("token_issued", user_id=settings.demo_username, expires_in=issued.expires_in)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)
