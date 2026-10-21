# syntax=docker/dockerfile:1
# text2sql-guard API. Configuration comes only from the environment (docker compose passes
# backend/.env; Azure passes Key Vault references); nothing secret is baked into the image.
# Base images are pinned by version AND digest: bump both together (see docs/threat-model.md).

# Debian 13: fewer unfixed OS findings than bookworm (Trivy: 44 vs 63 high/critical, 0 fixable).
ARG PYTHON_IMAGE=python:3.12.15-slim-trixie@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused until uv.lock changes.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
# Tokenizer file for prompt budgeting (otherwise downloaded at runtime or estimated).
RUN .venv/bin/python -m text2sql.llm.tokens

FROM ${PYTHON_IMAGE}
# The app runs from its own virtualenv: the system pip/setuptools/wheel are attack surface
# (and scanner findings) it never uses.
RUN python -m pip uninstall --yes --quiet pip setuptools wheel \
    && useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build --chown=root:root /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Root owns the code; the app user can only read it (the container also runs read-only).
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "text2sql.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
