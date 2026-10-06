# Phase 0 — Môi trường phát triển

Mục tiêu: có đủ công cụ để chạy mọi phase sau trên máy local.

| Thành phần | Phiên bản / ghi chú |
|---|---|
| OS | Ubuntu (hoặc WSL2) |
| Python | 3.12 (pin trong `.python-version`) |
| Quản lý package | [uv](https://docs.astral.sh/uv/) — `uv.lock` là nguồn chuẩn |
| Container | Docker + Docker Compose (chạy PostgreSQL) |

## 1. Cài uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version

# Nếu đã cài trước đó
uv self update
```

## 2. Cài dependency của project

```bash
make install        # = uv sync, cài cả nhóm dev (ruff, pytest, pyrefly, ...)
cp .env.example .env  # rồi sửa PG_PASSWORD
```

## 3. Cách project đã được khởi tạo (để tham khảo)

```bash
uv init retail-pulse --package --python 3.12
cd retail-pulse
uv python pin 3.12

# Generator (OLTP)
uv add sqlalchemy "psycopg[binary]" faker pydantic-settings
# Ingestion
uv add "dlt[snowflake]"
# Transform
uv add dbt-core dbt-snowflake
# Orchestration
uv add dagster dagster-dbt dagster-dlt
# Data quality
uv add great-expectations
# Dev tools
uv add --dev dagster-webserver ruff sqlfluff sqlfluff-templater-dbt pytest pre-commit pyrefly
```

## 4. Cấu trúc thư mục

```text
.
├── Makefile                  # lệnh thường dùng: make help
├── README.md                 # bài toán, data modeling, kiến trúc
├── assets/diagrams/          # hình dùng trong README
├── docs/
│   ├── README.md             # tổng quan + lộ trình theo phase
│   ├── Project-Spec.md       # đặc tả chuẩn của project
│   ├── phases/               # hướng dẫn chạy từng phase
│   └── design/               # thiết kế chi tiết từng thành phần
├── infras/
│   ├── docker-compose.yml
│   └── postgres/init/01_schema.sql
├── src/retail_pulse/
│   ├── oltp/                 # SQLAlchemy engine + ORM model
│   ├── generator/            # seed.py, stream.py, common.py
│   └── ingestion/            # dlt pipeline + clean
├── tests/                    # pytest
├── pyproject.toml
└── uv.lock
```

## 5. Kiểm tra code

```bash
make lint   # ruff check --fix + ruff format
make test   # bật Postgres rồi chạy pytest
```
