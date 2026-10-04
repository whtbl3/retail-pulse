.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f infras/docker-compose.yml
DAYS ?= 365
ROWS ?= 100000
DLT_PIPELINE ?= retail_oltp_to_snowflake

.PHONY: help install up down db-reset psql seed reseed lint

help: ## Liệt kê các lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Cài dependency theo uv.lock
	uv sync

up: ## Bật Postgres và chờ healthcheck
	$(COMPOSE) up -d --wait postgres

ingest-full: up ## Load lại toàn bộ từ đầu
	uv run ingest --full-refresh

down: ## Tắt container (giữ dữ liệu)
	$(COMPOSE) down

db-reset: ## Xóa volume, tạo lại DB từ 01_schema.sql
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait postgres

psql: ## Mở psql vào DB
	$(COMPOSE) exec postgres psql -U retail -d retail_oltp

seed: up ## Seed dữ liệu lịch sử (DAYS=365)
	uv run seed --days $(DAYS) --transactions $(ROWS)

reseed: up ## Xóa dữ liệu cũ rồi seed lại
	uv run seed --days $(DAYS) --transactions $(ROWS) --reset
	
lint: ## Ruff
	uv run ruff check --fix src && uv run ruff format src

clean-dlt: ## Xoá state cục bộ của dlt
	uv run python -m retail_pulse.ingestion.clean --local-only --yes

clean-snowflake: ## Xoá bảng trên Snowflake RAW (có hỏi xác nhận)
	uv run python -m retail_pulse.ingestion.clean --snowflake-only

clean-ingest: ## Dọn cả Snowflake RAW và state dlt (có hỏi xác nhận)
	uv run python -m retail_pulse.ingestion.clean