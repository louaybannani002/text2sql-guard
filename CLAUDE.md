# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**text2sql-guard**: a production-grade Text-to-SQL service. A natural-language question is turned
into SQL by an LLM, the SQL is checked by a guard layer, executed read-only, and returned with
full tracing.

## Repository layout

| Path        | Contents                                         |
|-------------|--------------------------------------------------|
| `backend/`  | Python 3.12 service, managed with **uv**          |
| `frontend/` | Web UI (not started yet)                          |
| `infra/`    | Terraform (not started yet)                       |
| `eval/`     | Evaluation datasets and harness                   |
| `docs/`     | Architecture notes and ADRs                       |

Backend packages under `backend/src/text2sql/`:

| Package         | Responsibility                                          |
|-----------------|---------------------------------------------------------|
| `config`        | `Settings` (pydantic-settings), read only from env vars |
| `db`            | Async DB connections, schema introspection              |
| `llm`           | LLM client abstractions                                 |
| `retrieval`     | Schema / few-shot context retrieval                     |
| `guard`         | Static + policy validation of generated SQL             |
| `executor`      | Read-only, sandboxed SQL execution                      |
| `pipeline`      | Orchestrates question → SQL → guard → execute           |
| `api`           | FastAPI HTTP layer (`create_app` factory)               |
| `cache`         | Caching of SQL and results                              |
| `observability` | Structured logging, tracing (Langfuse), metrics         |

## Commands (run from `backend/`)

```sh
make install     # uv sync --all-groups
make lint        # ruff check + ruff format --check
make format      # auto-fix
make typecheck   # mypy --strict
make test        # pytest (unit tests; `integration` marker deselected)
make run         # uvicorn with reload on 127.0.0.1:8000
make check       # lint + typecheck + test — must pass before every commit

make up          # start postgres (pgvector, pg16) + redis 7 from ../docker-compose.yml
make test-integration  # smoke tests against those services
make psql        # psql shell in the postgres container
make down        # stop services (`make down-volumes` also wipes data)
```

Local service credentials (`POSTGRES_*`, `REDIS_*`) live in `backend/.env` and must match
`DATABASE_URL` / `REDIS_URL`. SQL files in `backend/db/init/` run once, on an empty volume.

Without `make` (e.g. plain Windows), run the underlying `uv run …` commands from the Makefile.

## Conventions (non-negotiable)

1. **Async everywhere.** All I/O (DB, HTTP, LLM, cache) uses `async`/`await`. No blocking calls
   on the event loop; if a library is sync-only, wrap it with `asyncio.to_thread`.
2. **Typed code.** `mypy --strict` and `ruff` with `select = ["ALL"]` must pass. No bare `Any`,
   no `# type: ignore` without an error code and a reason.
3. **Small modules.** One responsibility per module; aim for < 200 lines. Prefer pure functions
   and small classes with explicit dependencies (pass them in, don't import globals).
4. **Every module has tests.** `tests/` mirrors `src/text2sql/` — `src/text2sql/guard/foo.py` is
   tested by `tests/guard/test_foo.py`. New code without tests is not done.
5. **No secrets in code.** All config comes from env vars via `text2sql.config.Settings`.
   Secrets are `SecretStr` with no default. Never hard-code, log, print or commit a secret.
   `backend/.env` is git-ignored; `.env.example` holds placeholders only. Tests use obviously
   fake values and never read `.env`.
6. **Structured logging only.** Use `text2sql.observability.logging.get_logger(__name__)` and log
   events with key/value context: `log.info("sql_generated", latency_ms=..., tokens=...)`.
   No `print`, no f-string log messages, no stdlib `logging` calls directly.

## Other rules

- Get settings through `get_settings()` at the edge (app startup) and pass them down explicitly.
- Public functions and classes have Google-style docstrings.
- Keep the dependency list lean; add a library only when it earns its place.
