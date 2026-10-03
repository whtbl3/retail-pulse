.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f infras/docker-compose.yml
DAYS ?= 365
ROWS ?= 100000

.PHONY: help install up down db-reset psql seed reseed lint

help: ## Liệt kê các lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Cài dependency theo uv.lock
	uv sync

up: ## Bật Postgres và chờ healthcheck
	$(COMPOSE) up -d --wait postgres

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
	uv run ruff check src
