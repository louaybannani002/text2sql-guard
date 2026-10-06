"""FastAPI application factory."""

from fastapi import FastAPI

from text2sql.config.settings import Settings, get_settings
from text2sql.observability.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Args:
        settings: Explicit settings (tests); defaults to the environment.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "development")

    app = FastAPI(title="text2sql-guard", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
