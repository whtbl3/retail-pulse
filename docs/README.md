# RetailPulse — Tài liệu

Trang này là điểm bắt đầu: project đang ở đâu, mỗi phase làm gì và đọc tài liệu nào.
Bài toán, data modeling và kiến trúc tổng thể nằm ở [README gốc](../README.md).
Đặc tả chuẩn (scope, data contract, acceptance criteria, decision log) là
[Project-Spec.md](Project-Spec.md); khi tài liệu khác mâu thuẫn với spec thì spec thắng.

## Luồng end-to-end

```text
seed.py / stream.py ──► PostgreSQL (OLTP, 3NF) ──dlt──► Snowflake RAW ──dbt──► staging ► marts (SCD2) ──► Preset
                                     Dagster điều phối ingest + transform
```

## Lộ trình theo phase

| Phase | Nội dung | Trạng thái | Tài liệu |
|---|---|---|---|
| 0 | Môi trường: uv, Docker, cấu trúc repo | Xong | [phases/00-environment-setup.md](phases/00-environment-setup.md) |
| 1 | PostgreSQL OLTP: schema, ORM, Docker Compose | Xong | [phases/01-oltp-database.md](phases/01-oltp-database.md) |
| 2 | Seed dữ liệu lịch sử (`seed.py`) | Xong | [phases/02-historical-seed.md](phases/02-historical-seed.md) |
| 3 | dlt ingestion full + incremental sang Snowflake RAW | Xong | [phases/03-ingestion-snowflake.md](phases/03-ingestion-snowflake.md) |
| 4 | Mô phỏng thay đổi giá sản phẩm (`stream.py`) | Xong | [phases/04-product-change-simulator.md](phases/04-product-change-simulator.md) |
| 5 | dbt: staging, SCD2, star schema | Xong | [phases/05-dbt.md](phases/05-dbt.md) |
| 6 | Dagster orchestration | Xong | [phases/06-dagster.md](phases/06-dagster.md) |
| 7 | Preset dashboards | Xong | [phases/07-preset.md](phases/07-preset.md) |
| 8 | Great Expectations: kiểm tra chất lượng RAW | Xong | [phases/08-great-expectations.md](phases/08-great-expectations.md) |
| 9 | DataOps: GitHub Actions, slim CI cho dbt | Xong | [phases/09-dataops-ci.md](phases/09-dataops-ci.md) |

## Thiết kế chi tiết theo thành phần

| Thành phần | Tài liệu | Code | Test |
|---|---|---|---|
| Data generator (seed + stream) | [design/data-generator.md](design/data-generator.md) | `src/retail_pulse/generator/` | `tests/test_seed.py`, `tests/test_stream.py` |
| Operational data modeling (OLTP: conceptual, logical, physical) | [design/operational-data-modeling.md](design/operational-data-modeling.md) | `infras/postgres/init/01_schema.sql`, `src/retail_pulse/oltp/` | — |
| Analytical data modeling (Kimball: process, grain, dimension, fact) | [design/analytical-data-modeling.md](design/analytical-data-modeling.md) | dbt (phase 5) | — |

## Chạy nhanh

Đến Postgres (chỉ cần Docker, chưa cần Snowflake):
```bash
make install              # cài thư viện (uv sync)
cp .env.example .env      # rồi sửa PG_PASSWORD
make up                   # bật PostgreSQL
make seed                 # nạp ~100k giao dịch lịch sử
make test                 # chạy toàn bộ test
```

Sang Snowflake, dbt và Dagster (cần cấu hình ở [phase 3](phases/03-ingestion-snowflake.md) và [phase 5](phases/05-dbt.md)):
```bash
make snowflake-init       # một lần: tạo warehouse, database, role, user
make ingest               # nạp Postgres sang Snowflake RAW
make dbt-deps && make dbt-build   # dựng staging đến marts và chạy test
make dagster              # mở giao diện Dagster để điều phối cả chuỗi
```
`make help` liệt kê mọi lệnh.

> **Cẩn thận:** `make seed`, `make reseed` và `make db-reset` đều **xóa RAW trên Snowflake** trước khi chạy. RAW là nơi
> duy nhất giữ lịch sử SCD2 của `product` và `employee`, nên xóa là mất lịch sử đó. Chi tiết ở [phase 2](phases/02-historical-seed.md).

## Quy ước tài liệu

- `docs/phases/NN-*.md`: hướng dẫn **chạy và kiểm tra** một phase: làm gì, lệnh nào, kết quả mong đợi.
- `docs/design/<thành-phần>.md`: **vì sao thiết kế như vậy** và hiện thực ra sao, dành cho người sửa code.
- Mỗi bước thao tác tay nêu rõ **vì sao làm** và **hậu quả nếu bỏ qua**. Khái niệm mới có mục "Đọc thêm" với đường dẫn đã kiểm tra còn sống.
- Viết ngắn, đúng thứ tự người đọc cần làm. Thuật ngữ kỹ thuật chuẩn (staging, incremental, SCD2...) giữ nguyên tiếng Anh.
- Khi xong một phase: thêm file trong `phases/`, cập nhật bảng ở trên và mục 14 của spec trong cùng thay đổi.
