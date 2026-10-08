# text2sql-guard

Production-grade Text-to-SQL: natural-language questions → LLM-generated SQL → guard checks →
read-only execution, with full observability.

A question passes an input guard (rules, then an AI classifier), schema retrieval, SQL
generation with a repair loop, an AST-based SQL validator and a read-only, cost-checked
executor running as a least-privilege database role. Answers stream live to a web UI.

## Layout

- [`backend/`](backend/) — Python 3.12 API (uv, FastAPI, asyncpg, LiteLLM, sqlglot, Redis)
- [`frontend/`](frontend/) — Next.js web UI (TypeScript, Tailwind, shadcn/ui, Playwright e2e)
- `infra/` — Terraform (TBD)
- `eval/` — evaluation datasets
- [`docs/`](docs/) — design docs

## Quick start

```sh
cd backend
cp .env.example .env    # fill in secrets; add "http://localhost:3000" to CORS_ALLOWED_ORIGINS
make install
make services           # postgres (pgvector) + redis only
make load-data          # migrate + load Olist CSVs from backend/data/raw/
make catalog            # schema docs + few-shot examples, with embeddings
make up                 # the whole app: db, cache, API (:8000), web UI (http://localhost:3000)
```

Then sign in at http://localhost:3000 with `DEMO_USERNAME` / `DEMO_PASSWORD` from `.env`.

Checks:

```sh
make check              # backend lint + types + unit tests
make test-integration   # backend tests against postgres + redis
make e2e                # Playwright end-to-end tests against the running stack
make lighthouse         # Lighthouse budget (performance, accessibility >= 90)
cd ../frontend && pnpm check
```

Conventions live in [CLAUDE.md](CLAUDE.md).

## License

[MIT](LICENSE)
