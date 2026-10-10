.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f infras/docker-compose.yml
DAYS ?= 365
ROWS ?= 100000
SALES ?= 300
DLT_PIPELINE ?= retail_oltp_to_snowflake
# dbt chạy từ dbt/, nạp .env trước vì profiles.yml dùng env_var(); dùng dbt trong .venv (qua uv run)
DBT := set -a && . ./.env && set +a && cd dbt && uv run dbt

.PHONY: help install up down ingest snowflake-init snowflake-init-dry db-reset psql seed reseed clean-raw stream stream-sales stream-loop test lint dbt-deps dbt-parse dbt-build dbt-test dbt-full-refresh dbt-docs quality dagster clean

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

stream-sales: up ## Như stream, thêm SALES (300) giao dịch bán mới rải trong giờ mở cửa kể từ giao dịch gần nhất
	uv run stream --sales $(SALES)

stream-loop: up ## Chạy stream liên tục đến khi Ctrl+C
	uv run stream --loop
	
test: up ## Chạy pytest (tạo DB tạm <PG_DB>_test, xóa sau khi xong)
	uv run pytest

lint: ## Ruff
	uv run ruff check --fix src && uv run ruff format src

clean-raw: ## Xoá RAW trên Snowflake + state dlt, không hỏi xác nhận
	uv run python -m retail_pulse.ingestion.clean --yes

quality: ## Great Expectations: kiểm tra chất lượng RAW (thoát mã 1 nếu có lỗi)
	uv run python -m retail_pulse.quality.raw_checks

dbt-deps: ## Cài package dbt (dbt_utils) vào dbt/dbt_packages
	$(DBT) deps

dbt-parse: ## Sinh dbt/target/manifest.json (Dagster cần file này; `make dagster` tự sinh, validate/chạy không dev thì không)
	$(DBT) parse

dbt-build: ## dbt build toàn dự án (model + test), cần RAW đã có dữ liệu
	$(DBT) build

dbt-test: ## Chỉ chạy test dbt
	$(DBT) test

dbt-full-refresh: ## Dựng lại fct_sales từ đầu (sửa dòng khóa -2); không đụng RAW
	$(DBT) build -s fct_sales --full-refresh

dbt-docs: ## Sinh và mở dbt docs (lineage) ở http://localhost:8080
	$(DBT) docs generate && $(DBT) docs serve

dagster: ## Mở Dagster (http://localhost:3000); lịch sử chạy mất khi tắt nếu chưa đặt DAGSTER_HOME
	uv run dagster dev

clean: ## Xóa file sinh ra (cache, dbt/target, dbt/logs); không đụng .env, .venv, key, dbt_packages
	rm -rf .pytest_cache .ruff_cache logs dbt/target dbt/logs dbt/package-lock.concurrent-update-lock
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
