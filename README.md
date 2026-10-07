# text2sql-guard

Production-grade Text-to-SQL: natural-language questions → LLM-generated SQL → guard checks →
read-only execution, with full observability.

> Status: scaffolding only. No business logic yet.

## Layout

- [`backend/`](backend/) — Python 3.12 API (uv, FastAPI, pydantic-settings, structlog)
- `frontend/` — web UI (TBD)
- `infra/` — Terraform (TBD)
- `eval/` — evaluation harness (TBD)
- [`docs/`](docs/) — design docs

## Quick start

```sh
cd backend
cp .env.example .env   # fill in secrets
make install
make up                 # postgres (pgvector) + redis via docker compose
make check
make load-data          # migrate + load Olist CSVs from backend/data/raw/
make catalog            # schema docs + few-shot examples, with embeddings
make ask Q="Revenue per month in 2018?"   # prints drafted SQL
make test-integration
make run
```

Conventions live in [CLAUDE.md](CLAUDE.md).

## License

[MIT](LICENSE)
