# syntax=docker/dockerfile:1
# text2sql-guard API. Configuration comes only from the environment (docker compose passes
# backend/.env); nothing secret is baked into the image.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused until uv.lock changes.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
# Tokenizer file for prompt budgeting (otherwise downloaded at runtime or estimated).
RUN .venv/bin/python -m text2sql.llm.tokens

FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "text2sql.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
