"""FastAPI dependencies: services, the authenticated user, rate limiting."""

from typing import Annotated

from fastapi import Depends, Request

from text2sql.api.auth import InvalidTokenError, Principal, verify_token
from text2sql.api.errors import ApiError
from text2sql.api.ratelimit import RateDecision
from text2sql.api.services import Services
from text2sql.observability.logging import bind_user

_BEARER = "bearer "
_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="text2sql-guard"'}


def get_services(request: Request) -> Services:
    """The process-wide services created by the lifespan handler."""
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def current_user(request: Request, services: ServicesDep) -> Principal:
    """Require a valid ``Authorization: Bearer <access token>`` header.

    Async on purpose: it runs in the request's own context, so the ``user_id`` it binds shows
    up on every later log line of the request (a sync dependency runs in a worker thread).
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(_BEARER):
        raise ApiError(401, "unauthorized", "Missing bearer token.", headers=_CHALLENGE)
    try:
        principal = verify_token(header[len(_BEARER) :].strip(), services.settings.jwt_secret)
    except InvalidTokenError:
        raise ApiError(
            401, "unauthorized", "Invalid or expired token.", headers=_CHALLENGE
        ) from None
    bind_user(principal.user_id)
    return principal


UserDep = Annotated[Principal, Depends(current_user)]


def rate_limit_headers(decision: RateDecision) -> dict[str, str]:
    """Standard-ish rate limit headers."""
    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(decision.retry_after_s)
    return headers


async def rate_limited_user(user: UserDep, services: ServicesDep) -> Principal:
    """The authenticated user, if they are under their per-minute request budget."""
    decision = await services.user_limiter.hit(user.user_id)
    if not decision.allowed:
        raise ApiError(
            429,
            "rate_limited",
            f"Too many requests: at most {decision.limit} per minute.",
            headers=rate_limit_headers(decision),
        )
    return user


LimitedUserDep = Annotated[Principal, Depends(rate_limited_user)]
