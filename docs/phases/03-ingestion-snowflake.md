# Phase 3 — Ingestion PostgreSQL → Snowflake RAW (dlt)

Mục tiêu: đưa dữ liệu OLTP sang Snowflake, lần đầu full load, các lần sau incremental.

| Bảng | Cách load | Khóa / cursor |
|---|---|---|
| `sales_transaction`, `sales_transaction_item`, `product`, `employee` | merge + incremental | khóa chính / `updated_at` |
| `store`, `category`, `brand`, `payment_method`, `promotion`, `promotion_product` | replace | toàn bảng |

Chi tiết hợp đồng ingestion: [Project-Spec.md, mục 9](../Project-Spec.md#9-ingestion-specification).
Code: `src/retail_pulse/ingestion/pipelines.py`, `src/retail_pulse/ingestion/clean.py`.

## 1. Tạo key pair cho user dlt

```bash
mkdir -p snowflake
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out snowflake/dlt_loader.p8 -nocrypt
openssl rsa -in snowflake/dlt_loader.p8 -pubout -out snowflake/dlt_loader.pub
grep -v -- '-----' snowflake/dlt_loader.pub | tr -d '\n'; echo # Lưu mã vừa rồi
```

## 2. Tạo warehouse, database, role, user trên Snowflake

```sql
USE ROLE ACCOUNTADMIN;
SELECT CURRENT_ACCOUNT();

-- Giới hạn chi phí
CREATE RESOURCE MONITOR IF NOT EXISTS RETAIL_RM
  WITH CREDIT_QUOTA = 10 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 80 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND;

CREATE WAREHOUSE IF NOT EXISTS RETAIL_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE RESOURCE_MONITOR = RETAIL_RM;

CREATE DATABASE IF NOT EXISTS RETAIL_PULSE;
CREATE SCHEMA IF NOT EXISTS RETAIL_PULSE.RAW;

-- Roles
CREATE ROLE IF NOT EXISTS LOADER;
CREATE ROLE IF NOT EXISTS TRANSFORMER;
GRANT ROLE LOADER TO ROLE SYSADMIN;
GRANT ROLE TRANSFORMER TO ROLE SYSADMIN;

-- LOADER: dlt ghi vào RAW
GRANT USAGE ON WAREHOUSE RETAIL_WH TO ROLE LOADER;
GRANT USAGE ON DATABASE RETAIL_PULSE TO ROLE LOADER;
GRANT CREATE SCHEMA ON DATABASE RETAIL_PULSE TO ROLE LOADER;
GRANT ALL ON SCHEMA RETAIL_PULSE.RAW TO ROLE LOADER;

-- TRANSFORMER: dbt đọc RAW, ghi các schema khác
GRANT USAGE ON WAREHOUSE RETAIL_WH TO ROLE TRANSFORMER;
GRANT USAGE ON DATABASE RETAIL_PULSE TO ROLE TRANSFORMER;
GRANT CREATE SCHEMA ON DATABASE RETAIL_PULSE TO ROLE TRANSFORMER;
GRANT USAGE ON SCHEMA RETAIL_PULSE.RAW TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES IN SCHEMA RETAIL_PULSE.RAW TO ROLE TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA RETAIL_PULSE.RAW TO ROLE TRANSFORMER;

-- User cho dlt
CREATE USER IF NOT EXISTS DLT_LOADER
  TYPE = SERVICE
  RSA_PUBLIC_KEY = ''
  DEFAULT_ROLE = LOADER
  DEFAULT_WAREHOUSE = RETAIL_WH;
GRANT ROLE LOADER TO USER DLT_LOADER;

DESC USER DLT_LOADER;
```

Sau khi chạy xong, kết quả trả về kèm `SHA256:...` là đã thành công.

Credential của dlt đặt trong `.dlt/secrets.toml` (không commit file này).

## 3. Full load lần đầu

```bash
make ingest-full
```

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
SHOW SCHEMAS IN DATABASE RETAIL_PULSE;   -- thấy RAW và RAW_STAGING (dlt tạo khi merge)

SELECT TABLE_NAME, ROW_COUNT
FROM RETAIL_PULSE.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'RAW'
ORDER BY TABLE_NAME;

```

## 5. Các lần sau: incremental

```bash
uv run ingest          # chỉ lấy dòng có updated_at mới hơn lần trước
make clean-ingest      # dọn RAW + state dlt nếu muốn làm lại từ đầu (có hỏi xác nhận)
```

Tiếp theo: [Phase 4 — Mô phỏng thay đổi giá sản phẩm](04-product-change-simulator.md).
