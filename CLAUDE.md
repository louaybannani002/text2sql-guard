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
make migrate     # apply pending SQL migrations
make load-data   # migrate, then (re)load the Olist CSVs into schema `shop`
make psql        # psql shell in the postgres container
make down        # stop services (`make down-volumes` also wipes data)
```

## Database & data

- Schema changes are **numbered SQL migrations** in `backend/db/migrations/NNNN_description.sql`,
  applied by `make migrate` (`text2sql.db.migrations`). Never hand-run SQL, and never edit an
  applied migration (its checksum is verified): add a new file instead.
- Analytics data lives in the Postgres schema `shop` (Olist e-commerce dataset). Every table and
  column has a `COMMENT` in plain business language; these feed the LLM, so any new table or
  column must get one too (an integration test enforces it).
- Raw CSVs go in `backend/data/raw/` (git-ignored, never committed). `make load-data` migrates,
  then truncates and reloads `shop` in one transaction (idempotent).
- Integration tests (`make test-integration`): see "Integration tests" below.

## Database roles (migration 0004)

| Role         | Login | Purpose / rights                                                          |
|--------------|-------|---------------------------------------------------------------------------|
| `t2s_owner`  | no    | Owns schemas `shop` and `app`. Migrations after 0004 run as it.           |
| `t2s_reader` | yes   | Executes LLM-generated SQL: SELECT on `shop` only, minus personal columns |
| `t2s_app`    | yes   | Application state: SELECT/INSERT/UPDATE/DELETE on schema `app` only       |

- `DATABASE_URL` (admin) is for migrations and loading only, never request handling.
  `READER_DATABASE_URL` / `APP_DATABASE_URL` hold the role passwords; `make migrate` syncs them.
- A new `shop` table is **not** readable by `t2s_reader` until its migration grants it — decide
  which columns are personal data first (grant column-by-column if any are).
- `t2s_reader`'s read-only mode and timeouts are session *defaults* the session itself can
  change (`SET`, `BEGIN READ WRITE`, `ALTER ROLE … SET`). Privileges are the real wall; the
  executor must still run each query in its own `READ ONLY` transaction with `SET LOCAL`
  limits, and the guard must reject anything but a single read-only statement.
- Unique / repeat customers are counted with `shop.customer_person.person_key` (materialized
  view, opaque dense_rank of the restricted `customer_unique_id`). Refresh materialized views
  after every data load: `make refresh-views` (`make load-data` does it automatically).

## Integration tests

`make test-integration` (marker `integration`; plain `make test` skips them):

- A session fixture runs `docker compose up --wait` once; no need to `make up` first.
- `text2sql_test` is a **persistent** shared database: migrated every session, reloaded only
  when the CSVs, loader code or migrations change (fingerprint), rebuilt automatically if an
  applied migration was edited. Safe to drop at any time; it is recreated.
- Use the `admin` / `reader` / `app` fixtures: session-long connections (logged in as the real
  roles) wrapped in a per-test transaction that is **always rolled back**. Never commit from a
  test on the shared database. Use `tests.integration.support.expect_failure` for statements
  that must fail (it uses a savepoint, so the test transaction survives).
- Only role-bootstrap tests (`test_role_bootstrap.py`) use `fresh_db`, a data-less database
  created and dropped per session.
- Use `127.0.0.1`, not `localhost`, in connection URLs: on Windows `localhost` tries IPv6
  first and costs ~2 s per connection.

## Generated SQL rules (binding for the future components)

- **Generated SQL must never use `SELECT *`** (nor `t.*`). Always name columns: personal-data
  columns are not readable by `t2s_reader`, so a star over `shop.customers` or `shop.sellers`
  fails at runtime, and a star elsewhere silently widens the result as the schema grows.
- **SQL validator (prompt 10)** must reject `*` or `tbl.*` in a select list over any relation
  that has columns `t2s_reader` cannot read, before the query reaches the database. `count(*)`
  is not a projection and is fine.
- **Schema catalog (prompt 7)** must include views and materialized views (e.g.
  `shop.customer_person`), not only tables, and must list **only the columns `t2s_reader` can
  actually read** — derive this from the database (`has_column_privilege('t2s_reader', …,
  'SELECT')`), never from a hard-coded list, so a new grant/revoke is picked up automatically.
  Restricted columns must not appear in prompts at all.

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
