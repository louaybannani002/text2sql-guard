.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test test-integration run check up services down down-volumes logs e2e lighthouse eval eval-smoke eval-compare psql migrate load-data refresh-views catalog ask

COMPOSE := docker compose -f ../docker-compose.yml --env-file .env

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install dependencies and cache the tokenizer (network, once)
	uv sync --all-groups
	uv run python -m text2sql.llm.tokens

lint: ## Lint and check formatting
	uv run ruff check src tests
	uv run ruff format --check src tests

format: ## Auto-fix lint issues and format
	uv run ruff check --fix src tests
	uv run ruff format src tests

typecheck: ## Static type check (strict)
	uv run mypy src tests

test: ## Run unit tests (no external services needed)
	uv run pytest

test-integration: ## Run smoke tests against the services from `make up`
	uv run pytest -m integration

run: ## Run the API locally with auto-reload (reads .env)
	uv run uvicorn text2sql.api.app:create_app --factory --reload

check: lint typecheck test ## Everything CI runs

up: ## Build and start the whole app (db, cache, API, web on http://localhost:3000)
	$(COMPOSE) up -d --build --wait

services: ## Start only postgres + redis (for `make run` and `pnpm dev`)
	$(COMPOSE) up -d --wait postgres redis

logs: ## Follow the API and web logs
	$(COMPOSE) logs -f api web

e2e: up ## Playwright end-to-end tests against the docker compose stack
	cd ../frontend && pnpm e2e

lighthouse: up ## Lighthouse audit (mobile + desktop) of the running web UI
	cd ../frontend && pnpm lighthouse

down: ## Stop services (data volumes are kept)
	$(COMPOSE) down

down-volumes: ## Stop services AND delete their data volumes
	$(COMPOSE) down -v

psql: ## Open a psql shell in the postgres container
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

migrate: ## Apply pending SQL migrations from db/migrations/
	uv run python -m text2sql.db migrate

load-data: migrate ## (Re)load the Olist CSVs from data/raw/ into shop, then refresh views
	uv run python -m text2sql.db load-olist
	$(MAKE) refresh-views

refresh-views: ## Refresh materialized views in shop (run after any data load)
	uv run python -m text2sql.db refresh-views

catalog: migrate ## Rebuild the retrieval catalog; re-embeds only what changed (FORCE=1: everything)
	uv run python -m text2sql.db $(if $(FORCE),catalog-force,catalog)

eval: ## Full evaluation (gold, attacks, benign) -> ../eval/reports/ (costs ~$2)
	uv run python ../eval/run_eval.py

eval-smoke: ## 20-question subset; exits 1 below the CI thresholds
	uv run python ../eval/run_eval.py --smoke

eval-compare: ## Main model vs local model (Ollama at LLM_LOCAL_API_BASE)
	uv run python ../eval/run_eval.py --model both

ask: ## Draft SQL for a question (not executed): make ask Q="How many orders per state?"
	uv run python -m text2sql.pipeline "$(Q)"
