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
| 5 | dbt: sources, staging, SCD2, marts | Chưa làm | — |
| 6 | Dagster orchestration | Chưa làm | — |
| 7 | Preset dashboards | Chưa làm | — |
| 8 | Great Expectations | Tùy chọn | — |

## Thiết kế chi tiết theo thành phần

| Thành phần | Tài liệu | Code | Test |
|---|---|---|---|
| Data generator (seed + stream) | [design/data-generator.md](design/data-generator.md) | `src/retail_pulse/generator/` | `tests/test_seed.py`, `tests/test_stream.py` |
| Operational data modeling (OLTP: conceptual, logical, physical) | [design/operational-data-modeling.md](design/operational-data-modeling.md) | `infras/postgres/init/01_schema.sql`, `src/retail_pulse/oltp/` | — |
| Analytical data modeling (Kimball: process, grain, dimension, fact) | [design/analytical-data-modeling.md](design/analytical-data-modeling.md) | dbt (phase 5) | — |

## Quick start

```bash
make install     # cài dependency (uv sync)
make up          # bật PostgreSQL
make seed        # nạp ~100k giao dịch lịch sử
make stream      # đổi giá vài sản phẩm
make ingest      # load sang Snowflake RAW, lần đầu load hết, sau đó incremental (cần cấu hình phase 3)
make test        # chạy toàn bộ test
make help        # liệt kê mọi lệnh
```

## Quy ước tài liệu

- `docs/phases/NN-*.md`: hướng dẫn **chạy và kiểm tra** một phase — làm gì, lệnh nào, kết quả mong đợi.
- `docs/design/<thành-phần>.md`: **vì sao thiết kế như vậy và hiện thực ra sao** — dành cho người sửa code.
- Khi xong một phase: thêm file `phases/`, cập nhật bảng ở trên và mục 14 của spec trong cùng thay đổi.
