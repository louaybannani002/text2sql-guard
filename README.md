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
make check
make run
```

Conventions live in [CLAUDE.md](CLAUDE.md).

## License

[MIT](LICENSE)
