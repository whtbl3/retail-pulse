# Phase 8 — Great Expectations (kiểm tra chất lượng RAW)

Mục tiêu: chặn dữ liệu xấu **ngay ở RAW**, trước khi dbt chạy. Theo
[Project-Spec](../Project-Spec.md), phase này là tùy chọn; dbt test vẫn là cơ chế chất lượng chính.

## Vì sao cần, khi đã có 168 test dbt
dbt test kiểm tra **sau** khi model đã build (staging, intermediate, marts). Nếu RAW có dòng xấu (khóa
rỗng, trạng thái lạ, số lượng âm), dbt vẫn build và có thể cho số liệu sai mà không báo. Great Expectations
(GE) kiểm tra RAW và, trong Dagster, **chặn không cho dbt chạy** khi RAW không đạt.

| | dbt test | Great Expectations |
|---|---|---|
| Kiểm tra ở đâu | staging, intermediate, marts | RAW |
| Khi nào | sau khi build model | trước khi dbt chạy |
| Nếu fail | model đã được build | dbt phía sau không chạy |

Không lặp lại thứ dbt đã làm: GE không kiểm `unique` hay `relationships` (RAW append-only nên trùng là
bình thường, staging đã dedup).

## Cái đã làm
- Code: `src/retail_pulse/quality/raw_checks.py`. Kiểm 4 bảng nạp incremental (dễ bẩn nhất):

| Bảng RAW | Phép kiểm |
|---|---|
| `sales_transaction` | có dòng; các cột khóa, `transaction_ts`, `updated_at` không rỗng; `status` thuộc `completed/cancelled/returned` |
| `sales_transaction_item` | có dòng; khóa, `product_id`, `quantity`, `regular_price` không rỗng; `quantity >= 1`; `regular_price >= 0`; `coupon_amount >= 0` |
| `product` | có dòng; `id`, `product_sku`, giá, giá vốn, `updated_at` không rỗng; `unit_price >= 0`; `unit_cost >= 0` |
| `employee` | có dòng; `id`, `store_id`, `updated_at` không rỗng; `salary >= 0` |

- Đọc bằng user `DBT_TRANSFORMER` (role `TRANSFORMER`, chỉ `SELECT` trên RAW), dùng cùng biến môi trường
  với dbt (`SNOWFLAKE_ACCOUNT`, `DBT_PRIVATE_KEY_PATH`).
- Dagster: `src/retail_pulse/orchestration/quality_checks.py` tạo mỗi bảng một **asset check** tên
  `great_expectations` với `blocking=True`. Check fail thì các asset phía sau (dbt) trong cùng run không chạy.
- Chạy tay: `make quality` (thoát mã 1 nếu có lỗi, in từng phép kiểm hỏng).

## Quyết định kỹ thuật
- **Không dùng datasource Snowflake của GE.** Nó cần `snowflake-sqlalchemy`, mà gói đó ép hạ cấp
  `sqlalchemy` từ 2.1 xuống 2.0 (dự án đã ghim `sqlalchemy>=2.1.2`). Thay vào đó đọc bảng về pandas rồi
  đưa cho GE: không đổi dependency nào.
- **Giới hạn:** kéo cả bảng về RAM, ổn ở vài trăm nghìn dòng (hiện RAW khoảng 290 nghìn dòng). Lên hàng chục
  triệu dòng thì phải đẩy phép kiểm vào Snowflake hoặc lấy mẫu. Đã ghi chú `ponytail:` trong code.
- Chỉ chọn cột cần kiểm và ép kiểu số về `float` trong SQL, vì Snowflake trả `NUMBER` dạng `Decimal`.

## Kiểm chứng
- `make quality`: cả 4 bảng `OK` trên dữ liệu hiện tại.
- `tests/test_raw_checks.py`: dữ liệu sạch thì đạt; dữ liệu có khóa rỗng và `status = 'refunded'` thì bị bắt
  (chứng minh phép kiểm thật sự phát hiện lỗi, không phải lúc nào cũng "xanh").
- Chạy job `full_pipeline`: 4 check `great_expectations` đều `passed`, rồi dbt chạy xong, `RUN_SUCCESS`.
- Khi dlt lỗi (Postgres tắt): 4 check và dbt đều bị bỏ qua vì phụ thuộc `retail_raw` đã fail.

**Chưa kiểm chứng:** chặn dbt khi chính check GE fail (chưa cố ý làm RAW bẩn, vì RAW là append-only và
không sửa tay). Cơ chế `blocking=True` là tính năng của Dagster, nhưng cần một lần thử thật nếu muốn chắc.

## Cách thêm phép kiểm
Sửa dict `TABLES` trong `raw_checks.py`: thêm `gxe.Expect...` vào danh sách của bảng. Bảng mới thì thêm
một mục (câu `SELECT` các cột cần kiểm + danh sách phép kiểm); asset check trong Dagster tự có theo `TABLES`.
