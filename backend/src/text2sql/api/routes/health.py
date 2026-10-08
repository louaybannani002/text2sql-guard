"""Liveness and readiness probes (no authentication, no rate limit)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from text2sql.api.dependencies import ServicesDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """The process is up. Never touches dependencies (a liveness probe must not cascade)."""
    return {"status": "ok"}


@router.get("/readyz", responses={503: {"description": "A dependency is unavailable."}})
async def readyz(services: ServicesDep) -> JSONResponse:
    """Postgres and Redis both answer within 2 s."""
    checks = await services.readiness()
    ready = all(state == "ok" for state in checks.values())
    body = {"status": "ok" if ready else "unavailable", "checks": checks}
    return JSONResponse(body, status_code=200 if ready else 503)
