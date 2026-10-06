.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test run check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies into .venv
	uv sync --all-groups

lint: ## Lint and check formatting
	uv run ruff check src tests
	uv run ruff format --check src tests

format: ## Auto-fix lint issues and format
	uv run ruff check --fix src tests
	uv run ruff format src tests

typecheck: ## Static type check (strict)
	uv run mypy src tests

test: ## Run the test suite
	uv run pytest

run: ## Run the API locally with auto-reload (reads .env)
	uv run uvicorn text2sql.api.app:create_app --factory --reload

check: lint typecheck test ## Everything CI runs
