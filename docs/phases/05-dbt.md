# Phase 5 — dbt (Snowflake RAW → staging → intermediate → marts)

Mục tiêu: biến dữ liệu RAW do dlt nạp thành star schema phân tích doanh số. Tiến độ theo lộ trình
trong `.claude/CLAUDE.md`; file này ghi lại từng bước đã làm.

| Bước | Nội dung | Trạng thái |
|---|---|---|
| 1 | Kết nối Snowflake, `dbt debug` pass | Xong |
| 2 | Khai báo sources | Xong |
| 3 | Staging + test | Xong |
| 4 | Intermediate: SCD2 product, employee | Chưa |
| 5 | Marts: dimension, `fct_sales` incremental | Chưa |
| 6 | Lineage, review | Chưa |

## Bước 1 — Kết nối và `dbt debug`

### Hiện trạng
- Project dbt nằm ở `dbt/` (tạo bằng `dbt init`), dùng dbt-core 1.12 và adapter Snowflake trong `.venv` (cài bằng `uv`). Máy còn một bản dbt 2.0.6 ở
  `~/.local/bin`; chọn một bản và dùng nhất quán, tài liệu này chạy bằng bản trong `.venv`.
- dlt đăng nhập bằng key pair (user `DLT_LOADER`, role `LOADER`, cấu hình trong `.dlt/secrets.toml`).
  dbt dùng cùng cách, nhưng với user và role riêng: `DBT_TRANSFORMER` / `TRANSFORMER`
  (tạo bởi `infras/snowflake/init.sql`), private key ở `.snowflake/dbt_transformer.p8`.

### Các file liên quan
| File | Vai trò | Commit? |
|---|---|---|
| `~/.dbt/profiles.yml` | **Cách kết nối**: account, user, key, role, warehouse, schema mặc định. Nằm ngoài repo, mỗi người một file | Không |
| `dbt/dbt_project.yml` | **Nội dung project**: tên, đường dẫn thư mục, `vars`, materialization và schema theo tầng | Có |
| `dbt/macros/generate_schema_name.sql` | Ghi đè cách đặt tên schema (xem bên dưới) | Có |
| `dbt/macros/surrogate_key.sql` | Macro sinh khóa thay thế (dùng ở bước marts) | Có |
| `.env` | Giá trị cho `env_var()` | Không |
| `.snowflake/*.p8` | Private key | Không |

`profiles.yml` không chứa bí mật dạng chuỗi. Hai giá trị thay đổi theo máy được lấy qua `env_var()`:

```yaml
retail_pulse:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: DBT_TRANSFORMER
      private_key_path: "{{ env_var('DBT_PRIVATE_KEY_PATH') }}"
      role: TRANSFORMER
      database: RETAIL_PULSE
      warehouse: RETAIL_WH
      schema: DBT_DEV
      threads: 4
```

Thêm vào `.env` (đã nằm trong `.gitignore`):

```
SNOWFLAKE_ACCOUNT=<org-account>
DBT_PRIVATE_KEY_PATH=/đường/dẫn/tuyệt/đối/.snowflake/dbt_transformer.p8
```

Key không có passphrase, nên không cần biến cho passphrase. Nếu sau này đặt passphrase, thêm
`private_key_passphrase: "{{ env_var('...') }}"`.

### Chạy `dbt debug`
dbt không tự đọc `.env`, nên nạp biến trước:

```bash
source .venv/bin/activate
cd dbt && set -a && . ../.env && set +a && dbt debug
```

Cách đọc kết quả:

| Phần trong output | Ý nghĩa |
|---|---|
| `Loading ~/.dbt/profiles.yml` / `Debugging profile` | Tìm thấy profile `retail_pulse`. Thiếu biến env thì lỗi hiện ở đây (`env_var ... not found`) |
| `Debugging connection` | Tham số dbt sẽ dùng: account, user, database, warehouse, schema, role |
| `Debugging connection test: OK` | Đã đăng nhập Snowflake thật bằng key |
| `Debugged All checks passed!` | Mọi kiểm tra đều đạt |

Kết quả mong đợi: `All checks passed`. IDE (tiện ích dbt) có thể báo `env_var 'SNOWFLAKE_ACCOUNT' not
found` vì nó không đọc `.env`. Đó không phải lỗi của file; chạy trong terminal vẫn bình thường.

### Quyết định cấu hình

**`threads: 4`.** Là số model dbt chạy song song. Thread bị giới hạn bởi DAG (model phụ thuộc phải
chờ nhau) và bởi warehouse (`RETAIL_WH` XSMALL có hàng chờ query). Tăng thread chỉ có ích khi DAG
có nhiều nhánh độc lập. Với dự án này 4 là đủ; muốn nhanh hơn thì cân nhắc size warehouse trước.

**Schema theo tầng, `generate_schema_name` ghi đè.** Mặc định dbt nối `target.schema` với schema
khai báo (`DBT_DEV_STAGING`). Macro của dự án bỏ phép nối đó:

| Tầng | `+schema` | `+materialized` | Lý do |
|---|---|---|---|
| staging | `staging` | view | Chỉ đổi tên, ép kiểu, dedup; nhẹ, không cần lưu |
| intermediate | `intermediate` | table | `int_product_scd2` dùng window function trên toàn bộ lịch sử và `fct_sales` join vào nó; tính một lần khi build, không tính lại mỗi lần query |
| marts | `marts` | table | Bảng cho dashboard |

`DBT_DEV` chỉ còn là schema dự phòng cho model không khai báo `+schema`.

> **Hạn chế đã biết:** vì macro bỏ phần nối `target.schema`, nếu thêm target `prod` dùng chung
> database `RETAIL_PULSE`, dev và prod sẽ ghi vào cùng `STAGING`, `INTERMEDIATE`, `MARTS`. Hiện chỉ
> có dev nên chưa ảnh hưởng. Khi thêm prod: cho macro rẽ nhánh theo `target.name`, hoặc dùng database
> riêng cho prod.

> **Cẩn thận chính tả config:** dbt không báo lỗi khi key có tiền tố `+` bị sai (ví dụ
> `+materialize` thay vì `+materialized`); model lặng lẽ rơi về mặc định (view). Kiểm tra bằng loại
> đối tượng thực tế được tạo ra.

## Bước 2 — Khai báo sources

File: `dbt/models/staging/___sources.yml`. Source là các bảng dbt không tự tạo (ở đây là bảng RAW do
dlt nạp). Khai báo một lần, model gọi bằng `{{ source('raw', '<bảng>') }}` thay vì gõ cứng tên bảng;
dbt nhờ đó vẽ được DAG từ nguồn và gắn test/freshness vào nguồn.

- Khai báo 10 bảng nghiệp vụ; bỏ qua các bảng nội bộ của dlt (`_dlt_loads`, `_dlt_version`,
  `_dlt_pipeline_state`) vì không dùng.
- Khóa chính lấy từ `PRIMARY KEY` trong `infras/postgres/init/`. Hai bảng có khóa ghép:
  `promotion_product (product_id, promotion_id)` và `sales_transaction_item (transaction_id, line_number)`.
- **Test ở source chỉ khẳng định điều luôn đúng ở nguồn.** Bảng replace: `unique` + `not_null` trên
  `id`. Bảng append (`product`, `employee`): chỉ `not_null`, vì `id` lặp lại qua các phiên bản.
  Khóa ghép: `not_null` từng cột; `unique` của tổ hợp kiểm ở staging.
- **Freshness** chỉ đặt cho `sales_transaction` (`loaded_at_field: created_at`, cảnh báo sau 1 ngày,
  lỗi sau 3 ngày). Không đặt cho `product`/`employee` vì chúng chỉ có dòng mới khi dữ liệu thay đổi,
  nên sẽ báo lỗi oan. Chạy bằng `dbt source freshness`, không chạy trong `dbt build`. Dữ liệu seed cũ
  nên lệnh này có thể báo lỗi; đó không phải lỗi của dbt.

Lưu ý cú pháp (bản dbt hiện tại): dùng `data_tests:` thay `tests:`, và `freshness`/`loaded_at_field`
nằm trong `config:`. Cú pháp cũ vẫn chạy nhưng bị cảnh báo deprecation.

Lỗi đã gặp: khai báo trùng một bảng (copy khối rồi sửa) gây lỗi `two sources with the name`.
Chạy `dbt parse` ngay sau khi sửa file yml để bắt sớm.

## Bước 3 — Staging

Staging là tầng sơ chế: mỗi bảng RAW một model `stg_<tên>`, chỉ làm việc nhẹ. Model chỉ chứa
`select`, đọc từ `source()`, materialize thành view trong schema `STAGING`.

### Việc staging làm và không làm
| Làm | Không làm |
|---|---|
| Đổi tên cột cho rõ nghĩa (`id` thành `store_id`) | Join, tính toán nghiệp vụ |
| Bỏ cột kỹ thuật `_dlt_*` và cột không dùng (`salary`) | Lọc giao dịch `completed` (làm ở tầng sau, ghi trong mô tả model) |
| Dedup bản sao ở biên cursor của dlt (bảng append) | Gộp các phiên bản SCD2 (giữ nguyên lịch sử) |

### Mười model
| Model | Kiểu nạp ở RAW | Dedup | Khóa kiểm tra |
|---|---|---|---|
| `stg_store`, `stg_category`, `stg_brand`, `stg_promotion`, `stg_payment_method` | replace | không | khóa chính: `unique` + `not_null` |
| `stg_promotion_product` | replace | không | `unique_combination_of_columns (promotion_id, product_id)` |
| `stg_product` | append | có | `(product_id, updated_at)` |
| `stg_employee` | append | có | `(employee_id, updated_at)` |
| `stg_sales_transaction` | append | có | `transaction_id` |
| `stg_sales_transaction_item` | append | có | `(transaction_id, line_number)` |

### Dedup bằng `QUALIFY`
```sql
select ... from {{ source('raw', 'product') }}
qualify row_number() over (
    partition by <mọi cột nghiệp vụ, gồm updated_at>
    order by _dlt_load_id desc
) = 1
```
- **Bản sao** là hai dòng giống hệt nhau về mọi cột nghiệp vụ, chỉ khác `_dlt_*`. **Phiên bản** là
  cùng id nhưng `updated_at` khác. Dedup phải loại bản sao và giữ mọi phiên bản.
- Cột thời gian của phiên bản (`updated_at`) phải nằm trong `partition by`. Nếu thiếu, nhân viên
  chuyển cửa hàng A, B, A sẽ bị gộp hai phiên bản A làm một và mất lịch sử. Test `unique` vẫn pass,
  nên lỗi này chỉ lộ ra khi tự nghĩ tình huống và kiểm tra.
- Gom theo mọi cột (thay vì chỉ `id` + `updated_at`) để hai dòng cùng khóa nhưng khác giá trị
  không bị chọn bừa mà làm test `unique` fail, tức lỗi được phát hiện.
- Thêm cột mới vào bảng nguồn thì phải thêm vào cả `partition by`.

### Test trong `___models.yml`
- **Khóa chính**: `unique` + `not_null`. **Bảng append**: `unique_combination_of_columns` trên
  `(id, updated_at)`, vì `id` một mình lặp lại.
- **`accepted_values`**: cột chỉ được nhận giá trị cho phép. Lấy danh sách từ `CHECK` của Postgres,
  không từ tài liệu: `promotion.type` là `percentage`, `fixed_amount` (không phải `fixed`),
  `status` là `completed`, `cancelled`, `returned`.
- **`relationships`**: đặt ở bảng con, trên cột khóa ngoại, trỏ tới bảng cha. Không đặt ở bảng cha.
  Giá trị rỗng bị bỏ qua nên khóa ngoại bắt buộc cần thêm `not_null`.
  Không đặt `relationships` từ `product_id` sang `stg_product` (nhiều dòng mỗi `product_id`); kiểm
  fact trỏ tới dim làm ở marts.
- Mỗi model và cột quan trọng có `description`, hiện ra trong `dbt docs`.

### Package `dbt_utils`
`unique_combination_of_columns` thuộc package `dbt_utils`, không có sẵn trong dbt. Khai báo ở
`dbt/packages.yml` rồi chạy `dbt deps` (tải vào `dbt_packages/`, đã ignore):

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.3.0", "<2.0.0"]
```

### Lệnh
```bash
cd dbt
dbt deps
dbt build -s staging    # 10 view, 53 test
```
Kết quả mong đợi: `PASS=63 ERROR=0`.

### Lỗi đã gặp
| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `No dbt_project.yml found` | Chạy dbt ở thư mục gốc repo | `cd dbt` trước |
| `'dbt_utils' is undefined` | Chưa khai báo/cài package | Tạo `packages.yml`, chạy `dbt deps` |
| `accepted_values` fail `FAIL 1` | Danh sách giá trị lệch thực tế (`fixed` vs `fixed_amount`) | Đối chiếu `CHECK` ở nguồn |
| Dedup làm mất phiên bản | `updated_at` thiếu trong `partition by` | Thêm vào `partition by` |
| Cảnh báo `UnusedResourceConfigPath` | `intermediate`/`marts` chưa có model | Tự hết khi có model |

> Đọc lỗi dbt: bắt đầu từ dòng `Error` đầu tiên (không phải cuối), xem file và giai đoạn (parse hay
> chạy SQL). Chi tiết ở `dbt/logs/dbt.log` và SQL biên dịch ở `dbt/target/compiled/`.

## Các bước còn lại
Bước 4 (SCD2 product và employee), bước 5 (dimension và `fct_sales` incremental) và bước 6
(lineage, review) sẽ được ghi vào file này khi hoàn thành.
