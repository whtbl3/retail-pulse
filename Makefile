.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f infras/docker-compose.yml
DAYS ?= 365
ROWS ?= 100000
DLT_PIPELINE ?= retail_oltp_to_snowflake

.PHONY: help install up down snowflake-init snowflake-init-dry db-reset psql seed reseed clean-raw stream stream-loop test lint

help: ## Liệt kê các lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Cài dependency theo uv.lock
	uv sync

up: ## Bật Postgres và chờ healthcheck
	$(COMPOSE) up -d --wait postgres

ingest: up ## Load Postgres sang Snowflake RAW (lần đầu load hết, sau đó incremental)
	uv run ingest

snowflake-init-dry: ## In các câu lệnh khởi tạo Snowflake, không kết nối
	uv run snowflake-init --dry-run

snowflake-init: ## Khởi tạo Snowflake (cần SNOWFLAKE_ACCOUNT, SNOWFLAKE_ADMIN_USER, SNOWFLAKE_ADMIN_PASSWORD)
	uv run snowflake-init

down: ## Tắt container (giữ dữ liệu)
	$(COMPOSE) down

db-reset: clean-raw ## Xóa volume Postgres + RAW Snowflake + state dlt, tạo lại DB
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait postgres

psql: ## Mở psql vào DB
	$(COMPOSE) exec postgres psql -U retail -d retail_oltp

seed: up clean-raw ## Seed dữ liệu lịch sử (DAYS=365); xóa RAW Snowflake trước
	uv run seed --days $(DAYS) --transactions $(ROWS)

reseed: up clean-raw ## Xóa dữ liệu cũ (Postgres + RAW Snowflake) rồi seed lại
	uv run seed --days $(DAYS) --transactions $(ROWS) --reset

stream: up ## Đổi giá vốn/giá bán của vài product (1 cycle)
	uv run stream

stream-loop: up ## Chạy stream liên tục đến khi Ctrl+C
	uv run stream --loop
	
test: up ## Chạy pytest (tạo DB tạm <PG_DB>_test, xóa sau khi xong)
	uv run pytest

lint: ## Ruff
	uv run ruff check --fix src && uv run ruff format src

clean-raw: ## Xoá RAW trên Snowflake + state dlt, không hỏi xác nhận
	uv run python -m retail_pulse.ingestion.clean --yes
