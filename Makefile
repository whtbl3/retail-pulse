.DEFAULT_GOAL := help
# REPO_DIR lets the Dagster containers mount .snowflake/ at the same absolute path as on the host
COMPOSE := REPO_DIR=$(CURDIR) docker compose --env-file .env -f infras/docker-compose.yml
DAYS ?= 365
ROWS ?= 100000
SALES ?= 300
DLT_PIPELINE ?= retail_oltp_to_snowflake
# dbt runs from dbt/ and loads .env first because profiles.yml uses env_var(); dbt comes from .venv (via uv run)
DBT := set -a && . ./.env && set +a && cd dbt && uv run dbt

.PHONY: help install up down ingest snowflake-init snowflake-init-dry db-reset psql seed reseed clean-raw stream stream-sales stream-loop test lint check dbt-deps dbt-parse dbt-build dbt-test dbt-full-refresh dbt-docs quality dagster dagster-up dagster-down dagster-logs clean

help: ## List the commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies from uv.lock
	uv sync

up: ## Start Postgres and wait for the healthcheck
	$(COMPOSE) up -d --wait postgres

ingest: up ## Load Postgres into Snowflake RAW (full load the first time, incremental after)
	uv run ingest

snowflake-init-dry: ## Print the Snowflake setup statements without connecting
	uv run snowflake-init --dry-run

snowflake-init: ## Set up Snowflake (needs SNOWFLAKE_ACCOUNT, SNOWFLAKE_ADMIN_USER, SNOWFLAKE_ADMIN_PASSWORD)
	uv run snowflake-init

down: ## Stop the containers (keeps data)
	$(COMPOSE) down

db-reset: clean-raw ## Delete the Postgres volume + Snowflake RAW + dlt state, recreate the DB
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait postgres

psql: ## Open psql on the DB
	$(COMPOSE) exec postgres psql -U retail -d retail_oltp

seed: up clean-raw ## Seed historical data (DAYS=365); deletes Snowflake RAW first
	uv run seed --days $(DAYS) --transactions $(ROWS)

reseed: up clean-raw ## Delete old data (Postgres + Snowflake RAW) and seed again
	uv run seed --days $(DAYS) --transactions $(ROWS) --reset

stream: up ## Change cost/price of a few products (1 cycle)
	uv run stream

stream-sales: up ## Like stream, plus SALES (300) new sales spread over opening hours since the latest sale
	uv run stream --sales $(SALES)

stream-loop: up ## Run stream continuously until Ctrl+C
	uv run stream --loop

test: up ## Run pytest (creates a temporary <PG_DB>_test DB, drops it afterwards)
	uv run pytest

lint: ## Ruff: autofix and format
	uv run ruff check --fix src tests .claude/hooks && uv run ruff format src tests .claude/hooks

check: ## Quality gate before opening a PR: ruff (no fixes) then pytest; same as CI
	uv run ruff check src tests .claude/hooks
	uv run ruff format --check src tests .claude/hooks
	$(MAKE) test

clean-raw: ## Delete Snowflake RAW + dlt state without confirmation
	uv run python -m retail_pulse.ingestion.clean --yes

quality: ## Great Expectations: check RAW data quality (exit code 1 on failure)
	uv run python -m retail_pulse.quality.raw_checks

dbt-deps: ## Install dbt packages (dbt_utils) into dbt/dbt_packages
	$(DBT) deps

dbt-parse: ## Generate dbt/target/manifest.json (Dagster needs it; `make dagster` builds it, non-dev validate/runs do not)
	$(DBT) parse

dbt-build: ## dbt build the whole project (models + tests); needs data in RAW
	$(DBT) build

dbt-test: ## Run dbt tests only
	$(DBT) test

dbt-full-refresh: ## Rebuild fct_sales from scratch (fixes -2 key rows); leaves RAW alone
	$(DBT) build -s fct_sales --full-refresh

dbt-docs: ## Generate and serve dbt docs (lineage) at http://localhost:8080
	$(DBT) docs generate && $(DBT) docs serve

dagster: ## Dev mode: Dagster in this terminal (http://localhost:3000); stop dagster-up first, both use port 3000
	uv run dagster dev

dagster-up: up ## Build and start the always-on Dagster UI (http://localhost:3000) and scheduler in Docker
	@$(COMPOSE) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '"'"'dagster'"'"'" | grep -q 1 || createdb -U "$$POSTGRES_USER" dagster'
	$(COMPOSE) up -d --build --wait dagster-webserver dagster-daemon

dagster-down: ## Stop the Dagster containers (keeps run history and Postgres running)
	$(COMPOSE) stop dagster-webserver dagster-daemon

dagster-logs: ## Follow the Dagster daemon and webserver logs
	$(COMPOSE) logs -f --tail 100 dagster-daemon dagster-webserver

clean: ## Delete generated files (caches, dbt/target, dbt/logs); keeps .env, .venv, keys, dbt_packages
	rm -rf .pytest_cache .ruff_cache logs dbt/target dbt/logs dbt/package-lock.concurrent-update-lock
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
