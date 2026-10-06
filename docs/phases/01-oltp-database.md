# Phase 1 — PostgreSQL OLTP

Mục tiêu: dựng database nguồn dạng 3NF mô phỏng hệ thống POS bán lẻ.
Lý do thiết kế (conceptual → logical → physical) nằm trong [README gốc](../../README.md#1-operational-data-modeling).

## Thành phần

| File | Vai trò |
|---|---|
| `infras/docker-compose.yml` | Container `postgres:16`, bật `wal_level=logical` cho CDC sau này |
| `infras/postgres/init/01_schema.sql` | DDL: schema `retail`, constraint, index, trigger `updated_at` |
| `src/retail_pulse/oltp/db.py` | Đọc cấu hình `PG_*` từ `.env`, tạo `engine` và `SessionLocal` |
| `src/retail_pulse/oltp/models.py` | ORM model khớp với DDL |

Quy ước chung của mọi bảng:

- Khóa chính `BIGINT GENERATED ALWAYS AS IDENTITY`.
- Có `created_at` và `updated_at` (`TIMESTAMPTZ`); trigger tự cập nhật `updated_at` mỗi khi UPDATE.
  Đây là cột mà dlt dùng làm cursor incremental.
- Tiền tệ dùng `NUMERIC(12, 2)` và `CHECK (>= 0)`.

## Chạy

```bash
make up        # bật Postgres, chờ healthcheck
make psql      # mở psql vào retail_oltp
make db-reset  # xóa volume và tạo lại DB từ 01_schema.sql (mất toàn bộ dữ liệu)
make down      # tắt container, giữ dữ liệu
```

`01_schema.sql` chỉ chạy khi volume còn trống, nên sau khi sửa DDL phải `make db-reset`.

## Kiểm tra

```sql
\dt retail.*                       -- 10 bảng
SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_%_updated_at';
```

Tiếp theo: [Phase 2 — Seed dữ liệu lịch sử](02-historical-seed.md).
