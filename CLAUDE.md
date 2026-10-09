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
| `frontend/` | Next.js UI (App Router, TS strict, Tailwind, shadcn/ui), pnpm |
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

make up          # build + start the whole app: postgres, redis, API (:8000), web UI (:3000)
make services    # postgres (pgvector, pg16) + redis 7 only, for `make run` / `pnpm dev`
make logs        # follow API and web container logs
make e2e         # make up, then Playwright end-to-end tests against the stack
make lighthouse  # make up, then Lighthouse (mobile + desktop); fails under 90
make test-integration  # smoke tests against those services
make migrate     # apply pending SQL migrations
make load-data   # migrate, then (re)load the Olist CSVs into schema `shop` + refresh views
make refresh-views  # refresh materialized views (e.g. shop.customer_person)
make catalog     # rebuild the retrieval catalog; re-embeds only changes (FORCE=1: all)
make ask Q="..." # answer a question end to end (executes as t2s_reader); exit 0/1/2/3/4
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

## LLM calls

- Every LLM call goes through `text2sql.llm.generate_structured(messages, ResponseModel, role)`.
  It returns `LLMResult(output, usage)`; log or persist `usage` (tokens, latency, cost, attempts).
- Roles `main` / `fast` / `local` map to LiteLLM model names in env (`LLM_MODEL_*`); never
  hard-code a model name in code. Catch `LLMError` (subclasses: timeout, provider, output
  validation — the latter carries `raw_output`, `errors` and the `usage` already spent).
- The API calls `text2sql.llm.warmup.warm_up` at startup: LiteLLM imports the provider SDK
  lazily on its first call, which would otherwise freeze the event loop inside a request.
- Import LiteLLM only via `text2sql.llm._litellm` (it pins the offline price map and disables
  telemetry before LiteLLM loads). Never log prompts or raw model output.
- Prompts live in `src/text2sql/llm/prompts/<name>_v<N>.system.md` + `.user.md` (a
  `string.Template`), loaded with `load_prompt("<name>_v<N>")`; the caller pins the version
  (e.g. `PROMPT_NAME = "generate_v1"` in `pipeline/generate.py`). Never change a released
  version's meaning in place — add `_v<N+1>` and switch the constant, so the change is one
  reviewable diff and old runs stay reproducible. User input goes only into the user template,
  inside tags (`<question>`), never into the system prompt.

## Retrieval catalog (`make catalog`)

- `text2sql.retrieval.build_catalog` introspects `shop` as `t2s_owner` and writes one document
  per relation (tables, views, materialized views) to `app.schema_docs`, with a pgvector
  embedding (HNSW) and a tsvector (GIN). Documents list only columns `t2s_reader` can read;
  free-text customer columns (`NO_EXAMPLE_VALUES` in `retrieval/catalog.py`) get no sample values.
- Few-shot examples live in `backend/db/seeds/examples.toml` (source of truth, human-reviewed)
  and are synced to `app.examples`. Tests parse every example, check the generation rules
  statically, and execute it as `t2s_reader` — a broken example fails the build.
- `schema_version` = hash of all documents. Embeddings are recomputed only for documents or
  examples whose content (or the embedding model) changed; `make catalog FORCE=1` re-embeds all.
  Run `make catalog` after any migration that changes `shop` or its comments.
- The embedding model must produce 1536-dimension vectors (`vector(1536)` in migration 0008).
- Views have no foreign keys: the catalog infers a join when a view column matches a table's
  single-column primary key by name and type (marked `inferred`, rendered as a comment).

## Retrieval (`retrieval/retriever.py`)

- `retrieve(question, k=5, ...)` runs as `t2s_app`: vector + full-text search in parallel,
  fused with Reciprocal Rank Fusion, top-k expanded along the FK graph with every relation
  needed to join them, plus the 3 most similar examples. Rendered as CREATE TABLE-style text
  within `RETRIEVAL_TOKEN_BUDGET`; detail is shed least-relevant-first (sample values, then
  column comments, then whole relations; never the top one).
- Token counts use tiktoken `o200k_base` from `backend/.cache/tiktoken` (filled by
  `make install`); without it a conservative estimate is used. Never call LiteLLM's
  `token_counter` (it downloads `cl100k_base` at runtime).
- Recall is evaluated on `eval/retrieval/questions.toml` (live test, target recall@5 >= 95%).
  Add a question there whenever retrieval misses a table in practice.
- The full flow lives in `pipeline/orchestrator.py` (see "Orchestrator" below). Only
  `ValidatedSql.sql` is ever executed; never run a draft directly.

## Input guard (`guard/input_guard.py`)

- `check_input(question)` runs before anything else. Layer 1 (`guard/input_rules.py`, no LLM):
  max 500 chars, no control/invisible characters, SQL *statement shapes* (`DROP TABLE`,
  `DELETE FROM`, `UPDATE … SET`, `GRANT SELECT … TO`), injection phrases, prompt-tag forgery;
  text is NFKC-normalised first. Layer 2 (`fast` model, prompt `input_guard_v2`) classifies
  `data_question | off_topic | prompt_injection | harmful`, only if layer 1 passed.
  The prompt (`input_guard_v2`) asks *what* is ignored, overridden or looked up: the data, the
  report or an order/product/seller id is a data question; the assistant's own rules, checks or
  role is an injection; a person's identity or whereabouts is harmful. Tune prompts on
  `eval/datasets/classifier_dev.jsonl` only; report with
  `python -m text2sql.eval.input_guard_eval --set test` (the attack block rate must stay 100%).
- Never match bare SQL keywords: "did revenue drop", "sellers grant installments" are real
  questions. Every new rule needs a benign counter-example in the tests.
- Fails closed (`guard_error`) when the classifier is unavailable. Blocks are logged with
  layer/category/rule and **never the question text**. User-facing reasons are ours, not the
  model's (which could echo the input).
- Labelled cases live in `eval/guard/input_cases.toml` (20 benign, 20 attacks); a live test
  runs all of them. Add every new bypass or false positive found in practice there.

## HTTP API (`text2sql.api`, `make run`)

| Endpoint              | Auth   | Purpose                                                        |
|-----------------------|--------|----------------------------------------------------------------|
| `POST /v1/auth/token` | —      | Demo user (`DEMO_USERNAME`/`DEMO_PASSWORD`) → HS256 JWT        |
| `POST /v1/query`      | Bearer | `{question}` → SSE stream (see below)                          |
| `GET /v1/schema`      | Bearer | Tables + readable columns, from `app.schema_docs`              |
| `POST /v1/feedback`   | Bearer | `{query_id, rating 1..5, comment}` → `app.feedback` (upsert)   |
| `GET /healthz`        | —      | Liveness (no I/O)                                              |
| `GET /readyz`         | —      | 200 / 503 with `{database, redis}` checks                      |

- **Stateless.** Queries go to `app.queries`, feedback to `app.feedback` (migration 0011), and
  rate-limit counters to Redis. Never keep request state in process memory. Pools and clients
  are created in the lifespan (`api/services.build_services`) and closed on shutdown. Routes see
  only the `Services` dataclass, so tests swap fakes in through `create_app(services_factory=…)`.
- **SSE events** on `/v1/query`, in order:
  1. `query` (`{query_id}`);
  2. the orchestrator events `stage_started` / `stage_done` / `error`;
  3. one final `answer`, or `server_error` if something unexpected happened.
  `sql` is sent only when the status is `answered`. `Answer.detail` and the trace's
  inputs/outputs are internal and are never sent. Messages to the user come from
  `pipeline/feedback.user_message`, never from raw DB error text.
- **Auth.** Access tokens live `JWT_ACCESS_TTL_S` (default 900 s) and carry iss, aud, exp, iat
  and jti. The signing algorithm is pinned on verification. There are no refresh tokens: clients
  log in again.
- **Rate limits** use a fixed one-minute window in Redis:
  - `RATE_LIMIT_PER_MINUTE` per user, on every `/v1/*` data route;
  - `AUTH_RATE_LIMIT_PER_MINUTE` per client IP on `/v1/auth/token`.
- **Errors** always have the shape `{"error": {code, message, request_id}}`.
  - Validation errors name only the fields involved and never echo the input.
  - Unexpected exceptions become a generic 500. `RequestIdMiddleware` swallows them and logs
    only the exception type, so neither the client nor the server log sees the message.
- **Middleware** is pure ASGI only (`BaseHTTPMiddleware` buffers SSE). From the outside in:
  1. request ID: `X-Request-ID` is kept if safe, otherwise generated;
  2. CORS: an explicit `CORS_ALLOWED_ORIGINS` list, no credentials;
  3. body limit: `MAX_REQUEST_BYTES`, checked against the declared size and the bytes actually
     received.
- OpenAPI docs are disabled when `APP_ENV=production`.

## Frontend (`frontend/`, pnpm)

- Next.js 16 (App Router, Turbopack, Cache Components), React 19, TypeScript strict
  (+ `noUncheckedIndexedAccess`), Tailwind v4, shadcn/ui, TanStack Table **v9** (`useTable`,
  explicit `tableFeatures`), Recharts, highlight.js (pgsql), zod, Vitest + Testing Library.
  `frontend/AGENTS.md`: this Next.js differs from older versions; read
  `node_modules/next/dist/docs/` before using an API you are unsure of.
- `pnpm check` (lint + typecheck + test) must pass before every commit; `pnpm build` too.
- All API access goes through `src/lib/api/client.ts`. Its zod schemas in `lib/api/types.ts`
  mirror the backend models: when `AnswerOut`, the SSE events or the error model change, update
  them in the same commit. The SSE stream is read with `fetch` + `SseParser` (`EventSource`
  cannot POST with a header).
- The JWT stays in memory (`TokenStore`), never in web storage or cookies. Never log tokens,
  questions or SQL in the browser console.
- The API's `guardrail` field (`api/guardrail.py`) tells the UI which layer stopped a question;
  `lib/guardrails.ts` holds the user-facing labels for its layers and codes. Add a label when a
  new input-rule category or validator rule appears.
- **Strict CSP** (`src/proxy.ts`, `lib/security/csp.ts`): a fresh nonce per request,
  `'strict-dynamic'`, no `'unsafe-inline'`/`'unsafe-eval'` (dev excepted), nonce-only
  `style-src`. Hence `cacheComponents` is off (a prerendered shell cannot carry a nonce) and
  the page renders per request. Other security headers live in `next.config.ts`.
  - Libraries must not eval or inject `<style>`/`<script>` at runtime: zod runs `jitless`
    (import `z` from `lib/api/zod.ts`, never from `"zod"`); sonner was removed for this.
  - The e2e fixture fails any test on a CSP violation or console error.
- E2E (`frontend/e2e/`, `pnpm e2e`): Playwright against the compose stack, real LLM included;
  desktop + mobile projects, axe WCAG 2.1 AA checks on each state, serial (shared demo user,
  real rate limits). Credentials come from the environment or `backend/.env`. Use
  `127.0.0.1`, not `localhost` (ports are IPv4-only; Node tries `::1` first).
- Lighthouse budget: performance and accessibility >= 90 on mobile and desktop
  (`pnpm lighthouse`). The results UI is lazy-loaded (`next/dynamic`) to keep the first load
  light; keep heavy libraries out of the sign-in path.
- Charts are only drawn when `lib/chart.ts` finds a date or category column plus numeric
  columns of a comparable scale; anything else shows the table only.

## Evaluation datasets (`eval/datasets/`, see its README)

- `gold.jsonl` (150 question/SQL pairs), `adversarial.jsonl` (60 attacks, each with the first
  layer that must stop it), `benign_tricky.jsonl` (30 suspicious-looking legitimate questions).
  Loaded and validated by `text2sql.eval.datasets`.
- Gold SQL follows the generation rules and the conventions of `db/seeds/examples.toml`, must
  pass the SQL validator, and must not repeat a few-shot question. Difficulty is checked against
  the SQL: easy = 1 table, medium = joins + aggregation, hard = window function or CTE.
- Rows with `review` set are ambiguous and await a human decision. Do not change a gold SQL's
  meaning silently: update `assumptions` / `review` with it.
- A false block found in practice goes into `benign_tricky.jsonl` (with `known_false_block` if it
  is not fixed yet); a bypass goes into `adversarial.jsonl`.

## Evaluation runs (`eval/run_eval.py`, logic in `text2sql.eval`)

- `make eval` runs the full pipeline (real models, database, cache) over `gold`, `adversarial`
  and `benign_tricky` and writes `eval/reports/<date>_<model>.md`, `.json` and
  `_failures.jsonl` (wrong answers with gold and predicted SQL, sample rows, internal detail).
  Reports are git-ignored. `make eval-compare` adds the local model (`--model both`; skipped
  with a note when Ollama is unreachable). `make eval-smoke` runs the 20-question subset in
  `eval/datasets/smoke.json` and exits 1 below its thresholds (accuracy >= 75%, attack block
  rate = 100%); CI runs it when the repo has the OPENAI_API_KEY / KAGGLE_* secrets.
- Execution accuracy (`eval/compare.py`): result sets compared as multisets; when the gold SQL
  sorts, only its ORDER BY columns must line up (ties may permute). Columns are matched by
  content (extra predicted columns are fine; gold `optional_columns` may be missing); numbers
  match at the less precise side's precision; percent vs fraction is accepted; labels may be
  renamed only when numeric columns pair the rows and a name used on both sides keeps its
  meaning. Every leniency has a test proving a wrong answer still fails: add one with any new
  leniency.
- An attack counts as blocked when a guardrail stops it (input rules, classifier, generator
  refusal, validator, executor limits, database); "answered safely" (validated read-only SQL
  ran) and pipeline failures are reported separately, never as blocks.
- Change `smoke.json` only with a reason: CI thresholds depend on it.

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

## SQL validator (`guard/sql_validator.py`)

- `validate(sql, policy)` -> `ValidatedSql | Rejection`, on the sqlglot AST (postgres dialect);
  **never regex**. Rules in order (`guard/sql_rules.py`): parse, single statement, read-only
  (no DML/DDL/DCL/Command node anywhere, incl. CTEs), no INTO/locks/COPY, tables (`shop` +
  allowlist, no system catalogs, schema-qualified), no `*`, functions (denylist + allowlist),
  cast types, columns (resolved through scopes with sqlglot's qualifier; personal columns and
  whole-row references rejected), then the outer LIMIT is capped at 1000.
- `SqlPolicy` comes from the database (`load_policy`, works as `t2s_app`): readable columns from
  the catalog, personal columns from `t2s_reader`'s real privileges. The unit-test fixture
  `tests/guard/fixtures/shop_policy.json` is checked against the live policy in integration.
- The function allowlist is built by parsing example calls (`guard/sql_functions.py`), because
  sqlglot renames functions (`date_trunc` -> `timestamp_trunc`) and models some operators and
  predicates (`AND`, `EXISTS`, `~`) as function nodes. To allow a function, add an example
  call there plus a test. Rejection reasons are fed back to the model; never put SQL in logs.

## Executor (`executor/executor.py`)

- `QueryExecutor.execute(validated_sql)` takes only `ValidatedSql`, runs as `t2s_reader` (pool on
  `READER_DATABASE_URL`). Per query: `SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`,
  then `EXPLAIN (FORMAT JSON)`: reject if the top-node cost > `EXECUTOR_MAX_COST` or the largest
  row estimate of ANY node > `EXECUTOR_MAX_PLAN_ROWS` (a LIMIT hides cross-join blow-ups from the
  top node). Rows come through a cursor capped at `EXECUTOR_MAX_ROWS` + 1 (`truncated` flag),
  converted to JSON-safe values. The transaction is ALWAYS rolled back, success or not.
- Database errors map to `ExecutionError` subclasses (`executor/errors.py`): timeout, too
  expensive, permission, read-only, invalid SQL, data error, unavailable. Catch those, never
  asyncpg exceptions, above the executor.
- Its tests start their own Postgres with Testcontainers (`tests/executor/test_executor.py`,
  real migrations and roles). Ryuk is disabled there (flaky on Docker Desktop for Windows).

## Orchestrator (`pipeline/orchestrator.py`)

- `answer(question, deps, on_event=None) -> Answer`: input guard -> retrieve -> generate ->
  validate -> execute. Statuses: answered, cannot_answer, blocked, rejected, failed. Expected
  failures never raise; LLM/catalog/database outages become `failed` with a safe message.
- Repair loop (`pipeline/attempts.py`): fixable failures (validator `Rejection.security=False`,
  `QueryInvalidError`, `QueryDataError`) go back to the generator (prompt `generate_v2`,
  `<previous_attempts>`) with the model's own SQL and the error, at most 2 retries.
  **Security rejections are never retried** (validator `security=True`, permission or
  read-only errors). Timeouts / cost rejections are not retried either.
- Every stage emits `stage_started`, `stage_done` or `error` events (`pipeline/events.py`) and
  is recorded in `Answer.trace` (input summary, output, latency, tokens, cost). The trace is
  for the caller; logs carry only counts and statuses, never SQL or questions.

## Cache (`cache/`, wired in by `pipeline/cache.py`)

- Two levels in Redis, looked up in a traced `cache` stage **after the input guard** (a cached
  answer never skips it):
  1. **Exact** (`cache/exact.py`): key = hash(normalised question, `schema_version`, prompt
     version, main model). Value = validated SQL, explanation, assumptions and the rows, TTL
     `CACHE_TTL_S`. A hit returns the stored rows without executing.
  2. **Semantic** (`cache/semantic.py`): cosine similarity >= `CACHE_SEMANTIC_THRESHOLD` (0.95)
     with an earlier question's embedding, **and** equal literal fingerprints (numbers and
     quoted strings, so "orders in 2017" never reuses the 2018 query). Only the SQL is reused;
     it is **executed again**. Plain Redis has no vector search: vectors are normalised float32
     in a hash, compared by dot product, at most `CACHE_SEMANTIC_MAX_ENTRIES` per namespace.
- Cached SQL is **always validated again** (`validate` stage, attempt 0) before it is used. If
  it no longer validates or fails to execute, the entry is dropped and the question takes the
  normal path.
- Invalidation is automatic: `schema_version`, `PROMPT_NAME`, the main model (and, for vectors,
  the embedding model) are part of every key, so `make catalog` or a prompt bump starts a fresh
  namespace. Old entries just expire. Bump `KEY_FORMAT` in `cache/keys.py` when an entry's
  shape changes. Results can be stale for up to `CACHE_TTL_S` after `make load-data`.
- The cache is global: every user runs SQL as the same `t2s_reader`. If per-user permissions
  are ever added, the user's role must become part of the keys.
- Only `answered` results are stored. Keys hold hashes, never question text. Redis errors are
  misses (stage output `error`), never failures. `Answer.cache` / the API's `cache` field say
  `exact`, `semantic` or null; the `cache` stage output has the per-level outcome and the best
  similarity. On a miss, the lookup's embedding is reused by retrieval (not paid twice).
- Unit tests use fakeredis; `tests/integration/test_cache_e2e.py` uses real Redis **database
  15** and flushes it. Never use database 15 for anything else.

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

## Docker compose (`docker-compose.yml`)

- Services: `postgres`, `redis`, `api` (`backend/Dockerfile`), `web` (`frontend/Dockerfile`), all
  published on 127.0.0.1 only. `api` and `web` run read-only, as non-root, with all capabilities
  dropped; `make up` waits until every healthcheck passes.
- `api` reads the same `backend/.env` as the host. `DATABASE_HOST=postgres:5432` and
  `REDIS_HOST=redis:6379` (set in compose only) replace the host in the URLs
  (`config/hosts.py`), so role passwords stay in one place. Never bake `.env` into an image:
  `.dockerignore` excludes it.
- `web` inlines `NEXT_PUBLIC_API_URL` (the API as the *browser* reaches it) at build time.
- The database is not initialised by compose: on an empty volume run `make migrate`,
  `make load-data` and `make catalog` from the host.
- Integration tests start only `postgres redis`, never the app containers.

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
