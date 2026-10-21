# Threat model

STRIDE review of text2sql-guard: a natural-language question becomes SQL written by an LLM,
which is checked and run against a database holding customer data. The central assumption:
**the LLM is not trusted**. It can be manipulated by the question (prompt injection) or simply
be wrong, so everything it produces is checked by code that does not depend on it.

## Assets

| Asset | Where | Why it matters |
|---|---|---|
| Customer personal data (`customer_unique_id`, zip prefixes, city/state of a person, seller identity columns) | Postgres schema `shop` | The main thing an attacker wants; must never leave through a query |
| Data integrity | `shop`, `app` | Generated SQL must never modify anything |
| Provider API keys (Gemini, Groq, OpenAI), Langfuse keys, DB role passwords, JWT secret | `backend/.env` (local), Key Vault (Azure), GitHub secrets (CI) | Theft means cost, data access or forged sessions |
| Free-tier quota and the cloud budget | Gemini, Groq, Azure | Denial of wallet: the cheapest attack on an LLM app |
| System prompts and internals | `llm/prompts/`, `Answer.detail`, traces | Help an attacker craft bypasses |
| Availability of the demo | API, Postgres, Redis | Expensive queries or floods take it down |

## Trust boundaries

```
 Browser ──(1)── Web (Next.js) ──(2)── API (FastAPI) ──(3)── LLM providers (Gemini, Groq)
                                        │  ├──(4)── Postgres: t2s_app (catalog, logs)
                                        │  ├──(5)── Postgres: t2s_reader (generated SQL only)
                                        │  └──(6)── Redis (cache, rate limits)
                                        └──(7)── Langfuse (traces)       CI / Azure: Key Vault (8)
```

1. Untrusted user input (the question) and an untrusted client. 2. Bearer-token API calls.
3. **The LLM's output is untrusted input** coming back in. 4/5. Two database roles with
different rights; generated SQL only ever runs as (5). 6. Cache content is re-validated before
use. 7. Telemetry leaves the system: it must carry no personal data or secrets. 8. Secrets are
injected at runtime, never baked into images.

## Threats and controls

### Spoofing

| Threat | Control |
|---|---|
| Calling the API without logging in | Bearer JWT on every `/v1/*` data route ([`api/dependencies.py`](../backend/src/text2sql/api/dependencies.py), [`api/auth.py`](../backend/src/text2sql/api/auth.py)): HS256 with the algorithm pinned on verification, `iss`/`aud`/`exp` checked, 15-minute tokens, no refresh tokens |
| Brute-forcing the demo password | Per-IP limit on `/v1/auth/token` ([`api/ratelimit.py`](../backend/src/text2sql/api/ratelimit.py), `AUTH_RATE_LIMIT_PER_MINUTE`) |
| Reading someone else's query or rating it | Feedback checks the query owner ([`api/routes/feedback.py`](../backend/src/text2sql/api/routes/feedback.py)) |
| Deploying as the owner | Deploys and demo start-up run in the protected GitHub Environment `production` with the owner as required reviewer; Azure login via OIDC federated credentials, no stored client secret (step 5) |

### Tampering

| Threat | Control |
|---|---|
| Prompt injection makes the model write `DROP`/`DELETE`/`UPDATE`/DDL | Four independent layers: (1) input rules reject statement shapes ([`guard/input_rules.py`](../backend/src/text2sql/guard/input_rules.py)); (2) the classifier flags injections ([`guard/input_guard.py`](../backend/src/text2sql/guard/input_guard.py)); (3) the sqlglot validator rejects any DML/DDL/DCL/command node anywhere, multi-statements, `INTO`, locks, `COPY` ([`guard/sql_rules.py`](../backend/src/text2sql/guard/sql_rules.py)); (4) the database: `t2s_reader` has SELECT only ([`0004_least_privilege_roles.sql`](../backend/db/migrations/0004_least_privilege_roles.sql)) and every query runs in a `READ ONLY` transaction that is always rolled back ([`executor/executor.py`](../backend/src/text2sql/executor/executor.py)) |
| A session changes its own limits (`SET`, `BEGIN READ WRITE`) | The validator rejects them; the executor re-applies `SET TRANSACTION READ ONLY` and `SET LOCAL statement_timeout` per query; privileges are the real wall |
| Poisoned cache entry (Redis written by someone else) | Cached SQL is validated again before every use; a semantic hit is executed again; an entry that no longer validates is dropped ([`pipeline/cache.py`](../backend/src/text2sql/pipeline/cache.py)). Redis needs a password and is not exposed (internal ingress on Azure) |
| Prompt injection through the database (a product description saying "ignore your rules") | Catalog sample values never include free-text customer columns ([`retrieval/catalog.py`](../backend/src/text2sql/retrieval/catalog.py), `NO_EXAMPLE_VALUES`); the user question sits only in the user template inside `<question>` tags; the validator does not care what the model was told |
| Supply chain: a compromised dependency or base image | Locked dependencies (`uv.lock`, `pnpm-lock.yaml`, frozen installs), base images pinned by digest, `pip-audit`, `pnpm audit` and Trivy in CI (`make security`) |

### Repudiation

| Threat | Control |
|---|---|
| "I never asked that" | Every query is stored with its user, status, SQL and timing in `app.queries` ([`api/store.py`](../backend/src/text2sql/api/store.py)); every log line has `request_id` and `user_id`; Langfuse keeps one trace per request (id = query id) |

### Information disclosure

| Threat | Control |
|---|---|
| Asking for personal data ("emails of customers in SP", `SELECT *` on customers) | Column privileges: `t2s_reader` cannot read personal columns at all; the catalog lists only columns `t2s_reader` can read, so the model never sees them ([`retrieval/catalog.py`](../backend/src/text2sql/retrieval/catalog.py)); the validator rejects personal columns, whole-row references and `*` ([`guard/sql_policy.py`](../backend/src/text2sql/guard/sql_policy.py), [`guard/sql_validator.py`](../backend/src/text2sql/guard/sql_validator.py)); the classifier flags "who is / where does X live" questions as harmful |
| Re-identifying customers by counting | Repeat-customer questions use `shop.customer_person.person_key`, an opaque rank of the restricted id ([`0006_customer_person.sql`](../backend/db/migrations/0006_customer_person.sql)) |
| Reading system catalogs (`pg_shadow`, `information_schema`) or other schemas | Validator allowlist: `shop` + listed relations, schema-qualified, no system catalogs; `t2s_reader` has no rights outside `shop` |
| Dangerous functions (`pg_read_file`, `dblink`, `lo_import`, `pg_sleep`) | Function denylist + allowlist built from example calls ([`guard/sql_functions.py`](../backend/src/text2sql/guard/sql_functions.py)) |
| Leaking the system prompt or internals | Prompt injection checks; user-facing messages are ours, never the model's or the database's (`pipeline/feedback.py`); `Answer.detail` and trace internals are never sent to clients |
| Secrets in logs, traces or images | `Settings` holds secrets as `SecretStr`; the log processor redacts question/SQL/rows/secret-like keys ([`observability/logging.py`](../backend/src/text2sql/observability/logging.py)); a pytest plugin scans the whole suite's captured output for secret formats ([`tests/support/log_secret_scan.py`](../backend/tests/support/log_secret_scan.py)); Langfuse gets no rows, prompts or raw output and a pseudonymous user id; Trivy's secret scanner checks both images; `.env` is git-ignored and excluded from Docker builds |
| Cross-site attacks in the browser | Strict CSP with per-request nonces, no `unsafe-inline`/`unsafe-eval` ([`frontend/src/proxy.ts`](../frontend/src/proxy.ts), [`lib/security/csp.ts`](../frontend/src/lib/security/csp.ts)); the JWT stays in memory, never in storage or cookies; CORS allows only the configured origins, no credentials ([`api/app.py`](../backend/src/text2sql/api/app.py)) |

### Denial of service

| Threat | Control |
|---|---|
| Query that scans or cross-joins billions of rows | `EXPLAIN` before running: reject if the top cost or any node's row estimate is over the limit (a `LIMIT` hides blow-ups from the top node); 5-second statement timeout; outer `LIMIT` capped at 1000; at most `EXECUTOR_MAX_ROWS` fetched ([`executor/executor.py`](../backend/src/text2sql/executor/executor.py), [`executor/plan.py`](../backend/src/text2sql/executor/plan.py)) |
| Request flood, huge bodies | Per-user rate limit on every data route, body size limit checked on declared and actual bytes ([`api/middleware.py`](../backend/src/text2sql/api/middleware.py)) |
| Denial of wallet: burning the LLM quota or the Azure budget | Rate limits; exact-cache hits skip every LLM call; the repair loop is capped at 2 retries; load tests run in fake LLM mode only; on Azure, apps scale to zero, `max_replicas` caps the API, Postgres is stopped between demos and a 15 USD budget triggers an automation that stops it (step 4) |
| Provider outage | Timeouts and bounded retries; Groq fallback on rate limits; the classifier fails closed |

### Elevation of privilege

| Threat | Control |
|---|---|
| Generated SQL acting as a powerful role | Three roles (migration 0004): `t2s_reader` (SELECT on `shop` minus personal columns) runs generated SQL; `t2s_app` (schema `app` only) runs the app; the admin URL is used only by migrations and loading |
| Container escape or tampering with the image at runtime | Non-root users (uid 10001 / distroless `nonroot`), code owned by root and read-only to the app, read-only root filesystem and all capabilities dropped in compose, `no-new-privileges`; distroless web runtime has no shell or package manager |
| Fake LLM mode left on in production | Refused at startup when `APP_ENV=production` ([`config/settings.py`](../backend/src/text2sql/config/settings.py)) |

## How the layers are tested

- `eval/datasets/adversarial.jsonl`: 60 attacks, each with the first layer that must stop it.
  The CI job **"Adversarial guardrails (offline)"** (a required check on `main`) replays every
  attack the input rules and the validator must stop, without any model. The classifier layer
  is measured by the smoke evaluation with live models (step 3).
- `eval/datasets/benign_tricky.jsonl`: 30 legitimate questions that look suspicious (false
  blocks are a failure too).
- Integration tests run every attack's SQL as the real `t2s_reader` role to prove the database
  wall holds even when the validator is bypassed.

## Dependency and image findings

`make security` (also in CI) fails on HIGH/CRITICAL findings that have a fix:

| Scan | Result (2026-10-21) | Decision |
|---|---|---|
| pip-audit, all Python dependencies | certifi 2026.7.22 (PYSEC-2026-4320) | fixed: upgraded to 2026.10.19 |
| pnpm audit, production dependencies | `braces` through `shadcn`, which was wrongly a runtime dependency | fixed: `shadcn` moved to devDependencies (it is a CSS import compiled at build time) |
| pnpm audit, dev dependencies | `braces` <= 3.0.3 (GHSA-vfj7-8cjw-p6xm, ReDoS-style stack exhaustion), no patched release | does not apply: only the shadcn CLI uses it, run by a developer on trusted input, never shipped; reported in CI as a warning |
| Trivy, API image | 44 HIGH/CRITICAL in Debian 13 base packages (util-linux, gzip, acl...), **0 with a fix** | moved from Debian 12 (63 findings) to 13; the app does not invoke these tools (no shell use, non-root, read-only); CI fails as soon as a fix is published |
| Trivy, web image | 0 (distroless Node on Debian 13; Debian 12's libssl3 had fixable findings) | fixed by the base image change |
| Trivy secret scanner, both images | none | `.env` is excluded by `.dockerignore`; config comes from the environment at runtime |
