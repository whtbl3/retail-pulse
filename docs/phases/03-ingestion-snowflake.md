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

dlt và dbt không nên chạy bằng tài khoản quản trị: một lỗi nhỏ trong code có thể xóa cả dữ liệu thô. Bước này dựng sẵn
"căn phòng" (database, warehouse) và các "chìa khóa" (role, user) với quyền vừa đủ, bằng một file SQL
([`infras/snowflake/init.sql`](../../infras/snowflake/init.sql)) chạy lại bao nhiêu lần cũng được.

### Chuẩn bị

Cần một user có role `ACCOUNTADMIN` và ba biến trong `.env` (xem `.env.example`): `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_ADMIN_USER`, `SNOWFLAKE_ADMIN_PASSWORD`. Thiếu `SNOWFLAKE_ACCOUNT` thì lệnh lấy `host` trong `.dlt/secrets.toml`.

*Vì sao `ACCOUNTADMIN`:* chỉ role này tạo được resource monitor, role và user.
*Nếu thiếu biến:* lệnh dừng với thông báo "Thiếu ..." và chưa tạo gì trên Snowflake.

### Chạy

```bash
make snowflake-init-dry   # xem trước, không kết nối Snowflake
make snowflake-init       # chạy thật
```

Lệnh tách file SQL thành từng câu, sinh cặp key cho mỗi user nếu chưa có (`.snowflake/<tên>.p8` và `.pub`), gắn
public key vào user rồi chạy lần lượt. Chạy lại an toàn vì mọi câu đều là `IF NOT EXISTS` hoặc `GRANT`; thứ đã có
không bị đổi, miễn là bạn giữ nguyên các file key.

### Những gì được tạo

| Thứ | Tên | Dùng để làm gì | Nếu thiếu |
|---|---|---|---|
| Resource monitor | `RETAIL_RM` | Trần 10 credit mỗi tháng, cảnh báo ở 80%, tự dừng ở 100% | Một truy vấn chạy sai có thể đốt hết credit |
| Warehouse | `RETAIL_WH` (XSMALL) | Máy tính cho mọi truy vấn; tự tắt sau 60 giây không dùng, tự bật lại khi cần | Không có chỗ chạy truy vấn; nếu không tự tắt thì tốn tiền lúc nhàn rỗi |
| Database | `RETAIL_PULSE` | Chứa toàn bộ dữ liệu của dự án | Không có chỗ lưu |
| Schema | `RAW` | Nơi duy nhất dlt ghi vào | dlt không có chỗ nạp |
| Schema | `STAGING`, `INTERMEDIATE`, `MARTS` | Các tầng của dbt, do role `TRANSFORMER` làm chủ | dbt tự tạo được ở lần build đầu; tạo sớm để cấp quyền đọc cho CI |
| Role | `LOADER`, `TRANSFORMER` | Phân quyền theo việc (bảng dưới) | Phải dùng chung một role quyền cao |
| User | `DLT_LOADER`, `DBT_TRANSFORMER` | Tài khoản của dlt và dbt, loại SERVICE, đăng nhập bằng key pair | Hai công cụ không có danh tính riêng để cấp quyền |

Phần cho CI (`RETAIL_PULSE_CI`, `CI_RUNNER`, `GITHUB_CI`) nằm cuối cùng file, giải thích ở [phase 9](09-dataops-ci.md).

### Ai được làm gì

| Role | `RAW` | `STAGING`, `INTERMEDIATE`, `MARTS` | Ghi chú |
|---|---|---|---|
| `LOADER` (dlt) | Đọc và ghi | Không có quyền | Được tạo schema, vì dlt có thể tạo schema tạm `RAW_STAGING` khi nạp |
| `TRANSFORMER` (dbt) | **Chỉ đọc** | Đọc và ghi (là chủ) | Không thể sửa hay xóa dữ liệu thô |

*Vì sao dbt chỉ đọc `RAW`:* RAW là nơi duy nhất giữ lịch sử SCD2 của `product` và `employee`. Nếu dbt ghi được vào đó,
một model viết sai có thể làm mất lịch sử không khôi phục được.

### Vì sao key pair, không dùng mật khẩu

Private key nằm ở máy bạn, Snowflake chỉ giữ public key; không có mật khẩu nào để lộ hay phải xoay vòng, và user loại
SERVICE không đăng nhập được bằng giao diện web. Đọc thêm:
[Snowflake: key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth).

### Kiểm tra

```sql
USE ROLE ACCOUNTADMIN;
DESC USER DLT_LOADER;                  -- cột RSA_PUBLIC_KEY_FP phải có dạng SHA256:...
SHOW GRANTS TO ROLE LOADER;            -- thấy quyền ALL trên schema RAW
SHOW SCHEMAS IN DATABASE RETAIL_PULSE; -- thấy RAW, STAGING, INTERMEDIATE, MARTS
```

*Nếu `RSA_PUBLIC_KEY_FP` trống:* public key chưa gắn vào user, dlt sẽ không đăng nhập được.

### Làm lại hoặc đổi key

Muốn tạo lại key cho một user: xóa **cả** `.p8` và `.pub` của user đó trong `.snowflake/`, chạy lại
`make snowflake-init`, rồi cập nhật `private_key` tương ứng (`.dlt/secrets.toml` cho dlt, file `.p8` mà
`DBT_PRIVATE_KEY_PATH` trỏ tới cho dbt). Lệnh chạy lại sẽ gắn public key mới, nên key cũ ngừng dùng được ngay.

### Lỗi thường gặp

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| "Thiếu SNOWFLAKE_ADMIN_USER..." | Chưa đặt biến môi trường | Điền trong `.env` hoặc `export` |
| Báo role `ACCOUNTADMIN` không được cấp cho user | User admin không có role này | Dùng user có `ACCOUNTADMIN` |
| dlt hoặc dbt báo lỗi xác thực (thường ghi `JWT token is invalid`) | Private key không khớp public key đã gắn, hoặc sai đường dẫn key | Kiểm tra `RSA_PUBLIC_KEY_FP`; nếu đã tạo lại key thì cập nhật cả hai nơi |

## 2. Cấu hình credential cho dlt

```bash
cp .dlt/secrets.toml.example .dlt/secrets.toml   # file thật, KHÔNG commit
```
Rồi điền `host` (account Snowflake) và `private_key` (key của `DLT_LOADER`); các trường còn lại
(`database = "RETAIL_PULSE"`, `username = "DLT_LOADER"`, `warehouse = "RETAIL_WH"`, `role = "LOADER"`) đã đúng sẵn trong file mẫu.

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
