"""FastAPI application factory.

Stateless: all shared state lives in Postgres (query log, feedback, catalog) or Redis (rate
limits); pools and clients are created in the lifespan handler and closed on shutdown.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from text2sql.api.errors import install_error_handlers
from text2sql.api.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from text2sql.api.routes import auth, feedback, health, query, schema
from text2sql.api.services import ServicesFactory, build_services
from text2sql.config.settings import Settings, get_settings
from text2sql.observability.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(
    settings: Settings | None = None, services_factory: ServicesFactory = build_services
) -> FastAPI:
    """Build the API application.

    Args:
        settings: Explicit settings (tests); defaults to the environment.
        services_factory: Builds pools/clients at startup; tests pass fakes.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "development")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = await services_factory(settings)
        app.state.services = services
        log.info("api_started", app_env=settings.app_env)
        try:
            yield
        finally:
            await services.close()
            log.info("api_stopped")

    app = FastAPI(
        title="text2sql-guard",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    for router in (health.router, auth.router, query.router, schema.router, feedback.router):
        app.include_router(router)

    # Last added runs first: request id -> CORS -> body size limit -> app.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,  # exact origins; empty list = none
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)
    return app
