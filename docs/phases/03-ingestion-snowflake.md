# Phase 3 — Ingestion PostgreSQL → Snowflake RAW (dlt)

Mục tiêu: đưa dữ liệu OLTP sang Snowflake; lần đầu nạp toàn bộ, các lần sau chỉ nạp phần mới.

| Bảng | Cách nạp | Khóa / cursor |
|---|---|---|
| `sales_transaction`, `sales_transaction_item`, `product`, `employee` | incremental, **append** | `updated_at` |
| `store`, `category`, `brand`, `payment_method`, `promotion`, `promotion_product` | replace (ghi đè) | toàn bảng |

> **Append, không merge.** Một dòng đổi (`product`, `employee`) thành một dòng **mới** trong RAW: cùng `id`, `updated_at`
> mới. RAW vì thế giữ mọi phiên bản và dbt dựng SCD2 từ đó. Hai hạn chế: mỗi cycle `stream.py` phải được ingest trước
> cycle kế tiếp (con trỏ chỉ thấy trạng thái cuối), và nguồn không có DELETE (con trỏ không thấy dòng bị xóa).

> **Cẩn thận: RAW là nơi duy nhất giữ lịch sử của `product` và `employee`.** Vì vậy `ingest` không có cờ
> `--full-refresh`. Làm lại từ đầu bằng `uv run clean-ingest` (có hỏi xác nhận) hoặc `make clean-raw` (không hỏi) rồi
> `make ingest` sẽ **xóa toàn bộ lịch sử**; chỉ làm khi chấp nhận mất.

Hợp đồng chi tiết: [Project-Spec, mục 9](../Project-Spec.md#9-ingestion-specification).
Code: `src/retail_pulse/ingestion/pipelines.py` (pipeline), `clean.py` (dọn RAW).

## 1. Khởi tạo Snowflake

Cần tài khoản `ACCOUNTADMIN`. Đặt `SNOWFLAKE_ADMIN_USER` và `SNOWFLAKE_ADMIN_PASSWORD` trong `.env` hoặc `export`
(`SNOWFLAKE_ACCOUNT` không đặt thì lấy từ `host` trong `.dlt/secrets.toml`).

```bash
make snowflake-init-dry   # xem trước các câu lệnh, không kết nối Snowflake
make snowflake-init       # chạy thật; chạy lại nhiều lần vẫn an toàn
```

Lệnh đọc `infras/snowflake/init.sql` và tạo: resource monitor, warehouse `RETAIL_WH` (XSMALL, tự tắt sau 60 giây),
database `RETAIL_PULSE`, schema `RAW`, role `LOADER` (dlt ghi vào RAW) và `TRANSFORMER` (dbt đọc RAW, ghi các tầng
khác), user `DLT_LOADER` và `DBT_TRANSFORMER`; phần dành cho CI nằm ở [phase 9](09-dataops-ci.md).
Mỗi user đăng nhập bằng key pair. Chưa có key trong `.snowflake/` thì lệnh tự tạo cặp mới (hoặc suy `.pub` từ `.p8`
có sẵn); `.snowflake/` nằm trong `.gitignore`.

*Vì sao tách role:* dlt chỉ cần ghi RAW, dbt chỉ cần đọc RAW và ghi các tầng sau. Mỗi bên chỉ có quyền vừa đủ.
*Nếu bỏ qua:* dùng một tài khoản quyền cao cho mọi việc thì một lỗi trong dbt có thể xóa RAW.

Kiểm tra: `DESC USER DLT_LOADER;` trong Snowsight, cột `RSA_PUBLIC_KEY_FP` phải có giá trị `SHA256:...`; trống nghĩa là
key chưa gắn và dlt không đăng nhập được.

## 2. Cấu hình credential cho dlt

Sao chép file mẫu `dlt/secrets.toml` thành `.dlt/secrets.toml` (file thật, **không commit**) rồi điền: `host` (account
Snowflake), `database = "RETAIL_PULSE"`, `username = "DLT_LOADER"`, `warehouse = "RETAIL_WH"`, `role = "LOADER"` và
`private_key` (key của `DLT_LOADER`).

*Về định dạng `private_key`:* dlt nhận chuỗi base64 của key, hoặc dùng `private_key_path` trỏ tới file PEM; xem
[tài liệu dlt cho Snowflake](https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake).
*Nếu bỏ qua:* `make ingest` dừng với lỗi thiếu cấu hình credential của destination Snowflake.

## 3. Nạp lần đầu

```bash
make ingest
```

Chưa có con trỏ incremental nên dlt nạp toàn bộ. Thành công khi cuối log có `... is LOADED and contains no failed jobs`
và danh sách số dòng, ví dụ lần nạp đầu của bộ seed mặc định:

| Bảng | Số dòng | Bảng | Số dòng |
|---|---|---|---|
| `sales_transaction` | 100.339 | `product` | 500 |
| `sales_transaction_item` | 286.797 | `employee` | 80 |
| `promotion_product` | 483 | `brand` | 30 |
| `category` | 10 | `store` | 10 |
| `payment_method` | 4 | `promotion` | 40 |

## 4. Kiểm tra trên Snowflake

```sql
USE ROLE ACCOUNTADMIN;
SHOW SCHEMAS IN DATABASE RETAIL_PULSE;     -- thấy RAW (và RAW_STAGING nếu dlt cần)

SELECT TABLE_NAME, ROW_COUNT
FROM RETAIL_PULSE.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'RAW'
ORDER BY TABLE_NAME;
```

## 5. Các lần sau: incremental

```bash
make ingest          # chỉ lấy dòng có updated_at mới hơn lần trước, ghi thêm (append)
```

Dagster cũng chạy đúng pipeline này ([phase 6](06-dagster.md)), dùng chung state dlt trong `~/.dlt/pipelines`.

## Đọc thêm

- [dlt: incremental loading](https://dlthub.com/docs/general-usage/incremental-loading): cursor `updated_at` hoạt động ra sao.
- [dlt: nguồn `sql_database`](https://dlthub.com/docs/dlt-ecosystem/verified-sources/sql_database): cách đọc bảng từ PostgreSQL.
- [Snowflake: key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth).

Tiếp theo: [Phase 4 — Mô phỏng thay đổi nguồn](04-product-change-simulator.md).
