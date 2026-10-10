# Phase 1 — PostgreSQL OLTP

Mục tiêu: dựng CSDL nguồn dạng 3NF mô phỏng hệ thống POS bán lẻ.
Vì sao thiết kế như vậy (conceptual → logical → physical): [Mô hình dữ liệu vận hành](../design/operational-data-modeling.md).

## Thành phần

| File | Vai trò |
|---|---|
| `infras/docker-compose.yml` | Container `postgres:16` |
| `infras/postgres/init/01_schema.sql` | DDL: schema `retail`, ràng buộc, index, trigger `updated_at` |
| `src/retail_pulse/oltp/db.py` | Đọc cấu hình `PG_*` từ `.env`, tạo `engine` và `SessionLocal` |
| `src/retail_pulse/oltp/models.py` | ORM model khớp với DDL |

`docker-compose.yml` bật sẵn `wal_level=logical` để dành cho CDC sau này; hiện chưa dùng vì CDC nằm ngoài phạm vi.

## Quy ước của mọi bảng

| Quy ước | Vì sao | Nếu bỏ qua |
|---|---|---|
| Khóa chính `BIGINT GENERATED ALWAYS AS IDENTITY` | Khóa tự tăng, ứng dụng không tự đặt | Khóa trùng hoặc đặt tay sai |
| `created_at` và `updated_at` (`TIMESTAMPTZ`), trigger tự cập nhật `updated_at` khi UPDATE | `updated_at` là cursor để dlt nạp incremental | UPDATE không đổi `updated_at` thì dlt không thấy thay đổi, RAW lệch nguồn |
| Tiền dùng `NUMERIC(12, 2)` kèm `CHECK (>= 0)` | Số thập phân chính xác; chặn tiền âm từ nguồn | `float` cho sai số cộng dồn; dữ liệu âm lọt vào analytics |

## Chạy

```bash
make up        # bật Postgres, chờ healthcheck
make psql      # mở psql vào retail_oltp
make down      # tắt container, giữ dữ liệu
make db-reset  # tạo lại DB từ 01_schema.sql
```

`01_schema.sql` chỉ chạy khi volume còn trống, nên sau khi sửa DDL phải `make db-reset`.
**`make db-reset` xóa luôn RAW trên Snowflake và state dlt**, không chỉ volume Postgres. RAW giữ lịch sử SCD2 nên
chỉ chạy khi chấp nhận mất lịch sử đó.

## Kiểm tra

```sql
\dt retail.*                       -- 10 bảng
SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_%_updated_at';
```

## Đọc thêm

- [PostgreSQL: trigger bằng PL/pgSQL](https://www.postgresql.org/docs/16/plpgsql-trigger.html): cách trigger `updated_at` hoạt động.
- [PostgreSQL: kiểu số](https://www.postgresql.org/docs/16/datatype-numeric.html): vì sao dùng `NUMERIC` cho tiền.
- [Docker Compose](https://docs.docker.com/compose/).

Tiếp theo: [Phase 2 — Seed dữ liệu lịch sử](02-historical-seed.md).
