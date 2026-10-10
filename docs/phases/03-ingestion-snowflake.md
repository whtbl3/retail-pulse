# Phase 3 — Ingestion PostgreSQL → Snowflake RAW (dlt)

Mục tiêu: đưa dữ liệu OLTP sang Snowflake, lần đầu full load, các lần sau incremental.

| Bảng | Cách load | Khóa / cursor |
|---|---|---|
| `sales_transaction`, `sales_transaction_item`, `product`, `employee` | incremental append | `updated_at` |
| `store`, `category`, `brand`, `payment_method`, `promotion`, `promotion_product` | replace | toàn bảng |

> **Append, không merge:** dòng đổi (`product`, `employee`) thành một dòng mới trong RAW, cùng
> `id` nhưng `updated_at` mới, nên RAW giữ nhiều phiên bản và dbt dựng SCD2 từ đó. Hạn chế:
> mỗi cycle `stream.py` phải được ingest trước cycle kế tiếp (con trỏ chỉ thấy trạng thái cuối),
> và nguồn không có DELETE (con trỏ không thấy dòng bị xóa).

> **Cảnh báo:** RAW là nơi duy nhất giữ lịch sử của `product` và `employee` (SCD2 dựng từ đó).
> Vì vậy `ingest` không có cờ `--full-refresh`. Muốn làm lại từ đầu, dùng `make clean-ingest` (có
> hỏi xác nhận) rồi chạy lại `make ingest`; việc đó **xóa toàn bộ lịch sử** nên chỉ làm khi chấp nhận
> mất lịch sử.

Chi tiết hợp đồng ingestion: [Project-Spec.md, mục 9](../Project-Spec.md#9-ingestion-specification).
Code: `src/retail_pulse/ingestion/pipelines.py`, `src/retail_pulse/ingestion/clean.py`.

## 1. Tạo key pair cho user dlt

```bash
mkdir -p .snowflake
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out .snowflake/dlt_loader.p8 -nocrypt
openssl rsa -in .snowflake/dlt_loader.p8 -pubout -out .snowflake/dlt_loader.pub
```

## 2. Tạo warehouse, database, role, user trên Snowflake

Toàn bộ nằm ở `infras/snowflake/init.sql` (resource monitor, warehouse `RETAIL_WH` XSMALL
auto-suspend 60 giây, database `RETAIL_PULSE`, schema `RAW`, role `LOADER` và `TRANSFORMER`, user
`DLT_LOADER` cho dlt và `DBT_TRANSFORMER` cho dbt, đều xác thực bằng key pair). File viết để chạy lại nhiều lần không lỗi.

```bash
make snowflake-init-dry   # in các câu lệnh, không kết nối Snowflake
# Chưa có key trong .snowflake/ thì snowflake-init tự tạo cặp mới (hoặc suy .pub từ .p8 có sẵn).
# Private key của dlt đặt trong .dlt/secrets.toml; của dbt là .snowflake/dbt_transformer.p8.
# Đặt SNOWFLAKE_ADMIN_USER và SNOWFLAKE_ADMIN_PASSWORD (tài khoản ACCOUNTADMIN) trong .env hoặc export.
# SNOWFLAKE_ACCOUNT không đặt thì lấy từ host trong .dlt/secrets.toml.
export SNOWFLAKE_ADMIN_USER=...  SNOWFLAKE_ADMIN_PASSWORD=...
make snowflake-init       # chạy thật bằng ACCOUNTADMIN, public key lấy từ .snowflake/dlt_loader.pub
```

Kiểm tra: chạy `DESC USER DLT_LOADER;` trên Snowflake, nếu cột `RSA_PUBLIC_KEY_FP` có giá trị
`SHA256:...` là key đã được gắn.

Credential của dlt đặt trong `.dlt/secrets.toml` (không commit file này).

## 3. Full load lần đầu

```bash
make ingest
```

Lần đầu chưa có con trỏ incremental nên dlt load toàn bộ.

```bash
Pipeline retail_oltp_to_snowflake load step finished in 18.71 seconds
1 load package(s) were loaded to destination snowflake and into dataset raw
The snowflake destination used snowflake://DLT_LOADER@EGYSTRV-PS95633/RETAIL_PULSE location to store data
Load package 1791044066.3043814 is LOADED and contains no failed jobs
Normalized data for the following tables:
- category: 10 row(s)
- sales_transaction: 100339 row(s)
- employee: 80 row(s)
- payment_method: 4 row(s)
- promotion: 40 row(s)
- sales_transaction_item: 286797 row(s)
- brand: 30 row(s)
- _dlt_pipeline_state: 1 row(s)
- store: 10 row(s)
- promotion_product: 483 row(s)
- product: 500 row(s)

Load package 1791044066.3043814 is NORMALIZED and NOT YET LOADED to the destination and contains no failed jobs
```
Kết quả như trên là đã thành công.

## 4. Kiểm tra trên Snowflake

```sql
USE ROLE ACCOUNTADMIN;
SHOW SCHEMAS IN DATABASE RETAIL_PULSE;   -- thấy RAW (và RAW_STAGING nếu dlt cần)

SELECT TABLE_NAME, ROW_COUNT
FROM RETAIL_PULSE.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'RAW'
ORDER BY TABLE_NAME;

```

## 5. Các lần sau: incremental

```bash
uv run ingest          # chỉ lấy dòng có updated_at mới hơn lần trước, ghi thêm (append)
make clean-ingest      # dọn RAW + state dlt nếu muốn làm lại từ đầu (có hỏi xác nhận)
```

Tiếp theo: [Phase 4 — Mô phỏng thay đổi giá sản phẩm](04-product-change-simulator.md).
