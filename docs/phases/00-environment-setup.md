# Phase 0 — Môi trường phát triển

Mục tiêu: có đủ công cụ để chạy mọi phase sau trên máy local.

| Thành phần | Yêu cầu |
|---|---|
| Hệ điều hành | Ubuntu hoặc WSL2 |
| Python | 3.12 (ghim trong `.python-version`) |
| Quản lý thư viện | [uv](https://docs.astral.sh/uv/); `uv.lock` là nguồn chuẩn |
| Container | Docker + Docker Compose (chạy PostgreSQL) |

## 1. Cài uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

*Vì sao uv:* một lệnh dựng đúng môi trường Python 3.12 và đúng phiên bản từng thư viện (khóa trong `uv.lock`).
*Nếu bỏ qua:* mỗi máy một phiên bản thư viện, lỗi "máy tôi chạy được" rất khó tái hiện.

## 2. Cài thư viện và cấu hình

```bash
make install               # = uv sync, cài cả nhóm dev (ruff, pytest, sqlfluff, ...)
cp .env.example .env       # rồi sửa PG_PASSWORD
```

*Vì sao `.env`:* giữ thông tin kết nối ngoài code. File này đã nằm trong `.gitignore`, không bao giờ commit.
*Nếu bỏ qua:* `make up` dừng ngay với thông báo thiếu `PG_USER` hoặc `PG_PASSWORD`.

`.env.example` liệt kê đủ mọi biến của dự án, chia nhóm theo phase. Lúc này chỉ cần nhóm PostgreSQL; nhóm Snowflake
điền khi tới [phase 3](03-ingestion-snowflake.md), mật khẩu Preset khi tới phase 7.

Danh sách thư viện nằm ở `pyproject.toml`, theo vai trò: generator (`sqlalchemy`, `psycopg`, `faker`), ingestion
(`dlt[snowflake]`), transform (`dbt-core`, `dbt-snowflake`), orchestration (`dagster`, `dagster-dbt`, `dagster-dlt`),
quality (`great-expectations`), dev (`ruff`, `pytest`, `sqlfluff`, `pre-commit`, `pyrefly`).

## 3. Kiểm tra môi trường

```bash
make lint   # ruff check --fix + ruff format trên src/
make test   # bật Postgres rồi chạy pytest (dùng DB tạm, xóa sau khi xong)
```

*Vì sao:* biết môi trường đúng trước khi làm tiếp, thay vì gặp lỗi lạ ở phase sau.
Lưu ý CI kiểm tra cả thư mục `tests/` (`ruff check src tests`), còn `make lint` chỉ chạy trên `src/`.

## Cấu hình và bí mật

Mọi thông tin đăng nhập nằm ngoài git. Với mỗi thứ, repo chỉ commit **file mẫu** để bạn biết bên trong có gì, còn
file thật bạn tự tạo từ mẫu.

| File thật (không commit) | File mẫu (có commit) | Bên trong có gì | Ai đọc |
|---|---|---|---|
| `.env` | `.env.example` | Kết nối PostgreSQL, account Snowflake, đường dẫn key của dbt, tài khoản admin (chỉ lúc khởi tạo), mật khẩu Preset | Python, Docker Compose, dbt, Great Expectations |
| `.dlt/secrets.toml` | `.dlt/secrets.toml.example` | Credential của user `DLT_LOADER` | dlt |
| `~/.dbt/profiles.yml` | `dbt/profiles.yml.example` | Cách dbt kết nối Snowflake (chỉ tham chiếu biến môi trường) | dbt |
| `.snowflake/*.p8` | không có mẫu | Private key của từng user, do `make snowflake-init` sinh ra | dlt, dbt, CI |
| GitHub Secrets | xem [phase 9](09-dataops-ci.md) | `SNOWFLAKE_ACCOUNT`, `CI_PRIVATE_KEY` | CI |

*Vì sao tách mẫu và bản thật:* người đọc thấy ngay cần cấu hình những gì mà không có bí mật nào lọt lên git.
*Nếu commit file thật:* repo này public, nên ai cũng đọc được; key hay mật khẩu bị lộ thì phải đổi ngay, xóa
commit sau đó không thu hồi được.

Kiểm tra nhanh trước khi commit: `git status` không được liệt kê `.env`, `.dlt/secrets.toml` hay file `.p8`.

## Cấu trúc thư mục

```text
.
├── Makefile                  # lệnh thường dùng: make help
├── README.md                 # bài toán, mô hình dữ liệu, kiến trúc
├── pyproject.toml, uv.lock   # thư viện và phiên bản
├── .env.example              # mẫu cấu hình: PostgreSQL, Snowflake, Preset (bản thật là .env, không commit)
├── .github/workflows/        # CI: ci.yml, manifest.yml
├── assets/diagrams/          # hình dùng trong tài liệu
├── .dlt/secrets.toml.example # mẫu credential của dlt (bản thật là .dlt/secrets.toml, không commit)
├── dbt/                      # dự án dbt: models, tests, macros, ci/profiles.yml, profiles.yml.example
├── docs/
│   ├── README.md             # tổng quan và lộ trình theo phase
│   ├── Project-Spec.md       # đặc tả chuẩn của dự án
│   ├── phases/               # hướng dẫn chạy từng phase
│   └── design/               # thiết kế chi tiết từng thành phần
├── infras/
│   ├── docker-compose.yml
│   ├── postgres/init/01_schema.sql
│   └── snowflake/init.sql
├── src/retail_pulse/
│   ├── oltp/                 # SQLAlchemy engine và ORM model
│   ├── generator/            # seed.py, stream.py, common.py
│   ├── ingestion/            # pipeline dlt, dọn RAW, khởi tạo Snowflake
│   ├── orchestration/        # Dagster: asset dlt và dbt, job, lịch chạy
│   └── quality/              # Great Expectations kiểm tra RAW
└── tests/                    # pytest
```

## Đọc thêm

- [uv: làm việc với dự án](https://docs.astral.sh/uv/concepts/projects/layout/) và
  [`uv sync`](https://docs.astral.sh/uv/concepts/projects/sync/): vì sao có `uv.lock` và cách đồng bộ môi trường.
- [Ruff](https://docs.astral.sh/ruff/) (lint và format) và [pytest](https://docs.pytest.org/en/stable/).

Tiếp theo: [Phase 1 — PostgreSQL OLTP](01-oltp-database.md).
