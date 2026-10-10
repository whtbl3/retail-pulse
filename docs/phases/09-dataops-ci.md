# Phase 9 — DataOps: GitHub Actions và slim CI cho dbt

Mục tiêu: mỗi pull request tự kiểm tra thay đổi dbt mà **không đụng dữ liệu thật** và **không build lại
toàn bộ**. Khớp khối "GitHub CI" trong [README gốc](../../README.md).

## Slim CI là gì
Build lại toàn bộ dbt cho mỗi PR thì chậm và tốn credit. Slim CI chỉ build **model bị sửa và mọi model phụ
thuộc vào chúng** (`state:modified+`); model không đổi thì đọc từ bản thật (`--defer`).

```bash
dbt build --select state:modified+ --defer --state <thư mục chứa manifest.json của bản thật>
```

`manifest.json` là bản chụp DAG của một lần parse. dbt so manifest của PR với manifest của bản thật để biết
model nào đổi. Nối với kiến thức cũ: `ref()` tạo DAG, nên dbt biết "sửa `dim_product` thì `fct_sales` bị ảnh
hưởng".

## Thiết kế (an toàn trước, rẻ sau)

| Vấn đề | Cách xử lý |
|---|---|
| CI không được ghi đè dữ liệu thật | Database riêng `RETAIL_PULSE_CI`; user `GITHUB_CI` chỉ có quyền **đọc** `RETAIL_PULSE` |
| Nhiều PR chạy song song | Schema theo PR: `PR_<số>_STAGING`, `PR_<số>_MARTS`... (macro `generate_schema_name` chỉ đổi khi target là `ci`, dev/prod giữ nguyên) |
| CI sinh rác | Bước cuối (`if: always()`) chạy `dbt run-operation drop_ci_schemas`; macro **từ chối chạy** nếu target không phải `ci` |
| CI chạy sai ăn hết credit | Warehouse riêng `RETAIL_CI_WH` + resource monitor `RETAIL_CI_RM` (2 credit/tháng, tự suspend ở 100%) |
| Lộ bí mật | Xác thực key pair, private key chỉ nằm trong GitHub Secrets, ghi ra file tạm quyền 600; secret truyền qua biến môi trường, không nhúng vào lệnh shell |
| Quyền workflow | `permissions` tối thiểu (`contents: read`, `actions: read`); PR từ fork không nhận secret nên không chạy được phần Snowflake (chủ ý) |
| Hai PR đẩy liên tiếp | `concurrency` hủy lần chạy cũ của cùng PR |

## Các file
| File | Việc |
|---|---|
| `.github/workflows/ci.yml` | Mỗi PR: lint (`ruff`) + slim CI dbt + dọn schema |
| `.github/workflows/manifest.yml` | Mỗi lần merge vào `main` (có đổi `dbt/`): `dbt parse --target prod` rồi lưu `manifest.json` làm artifact `prod-manifest` |
| `dbt/ci/profiles.yml` | Profile cho CI (target `ci` và `prod`), chỉ dùng biến môi trường, được phép commit |
| `dbt/macros/generate_schema_name.sql` | Thêm nhánh `ci` (tiền tố PR) |
| `dbt/macros/drop_ci_schemas.sql` | Xóa schema của PR |
| `infras/snowflake/init.sql` | (phần CI ở cuối file) tạo database/warehouse/role/user cho CI; chạy cùng `make snowflake-init` |

Luồng một PR: lấy manifest mới nhất của `main` (nếu chưa có thì build toàn bộ) → `dbt build
--select state:modified+ --defer` vào `RETAIL_PULSE_CI.PR_<số>_*` → xóa schema.

## Thiết lập (làm một lần)

**1-2. Tạo key pair và môi trường CI trên Snowflake: một lệnh.** Phần CI nằm cuối `infras/snowflake/init.sql`
nên chạy cùng khởi tạo chung (xem [phase 3](03-ingestion-snowflake.md)):
```bash
make snowflake-init       # chạy lại an toàn; tự tạo .snowflake/github_ci.p8 và .pub nếu chưa có
```
Schema `STAGING`, `INTERMEDIATE`, `MARTS` được tạo bằng role `TRANSFORMER` (để dbt vẫn làm chủ sở hữu) rồi mới
cấp quyền đọc cho `CI_RUNNER`, nên chạy được ngay cả khi dbt chưa build lần nào.

**3. Thêm hai secret vào GitHub** (Settings, Secrets and variables, Actions):
- `SNOWFLAKE_ACCOUNT`: account identifier (như trong `.env`).
- `CI_PRIVATE_KEY`: toàn bộ nội dung `.snowflake/github_ci.p8`, gồm cả dòng BEGIN/END.

**4. Bật workflow:** push các file lên `main`. Workflow `Prod manifest` chạy và tạo artifact đầu tiên. Sau đó
mở một PR thử có sửa một model để xem slim CI chạy.

`.snowflake/` đã nằm trong `.gitignore`; dán xong vào GitHub thì giữ file ở máy hoặc xóa đều được.

## Lưu ý
- **Manifest lệch bản thật:** manifest được sinh khi merge vào `main`, trong khi dữ liệu thật do Dagster build
  trên máy bạn. Nếu merge xong mà chưa chạy `full_pipeline`, PR kế tiếp so với code mới nhưng `--defer` đọc
  bảng thật còn cũ. Với dự án một người thì chấp nhận được; nhiều người thì cần deploy tự động.
- **`fct_sales` là incremental:** schema CI mới chưa có bảng nên lần build đầu chạy đầy đủ (khoảng 270 nghìn
  dòng, nhẹ). Đây cũng là cách kiểm tra lần build từ đầu.
- **Action chưa ghim theo mã commit** (`actions/checkout@v4`...). Best practice mạnh hơn là ghim SHA và để
  Dependabot cập nhật.
- Chưa có `sqlfluff lint` và `pytest` trong CI: `pytest` cần manifest và profile dbt, `sqlfluff` với templater
  dbt cần kết nối. Thêm khi cần.

## Kiểm chứng
Đã kiểm tra ở máy: YAML của workflow và profile hợp lệ; `dbt parse --target ci` biên dịch macro mới và ghi
đúng `RETAIL_PULSE_CI.PR_7_marts`; target dev vẫn ghi `RETAIL_PULSE.marts` (không đổi hành vi);
toàn bộ test Python vẫn đạt (53).

**Chưa kiểm chứng:** việc chạy thật trên GitHub Actions và trên Snowflake (cần bước thiết lập ở trên).
