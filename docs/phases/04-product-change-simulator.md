# Phase 4 — Mô phỏng thay đổi giá sản phẩm (`stream.py`)

Mục tiêu: tạo thay đổi nhỏ, thực tế trên bảng `product` để dlt load incremental và sau này
dbt snapshot ghi lịch sử SCD2 cho `dim_product`.
Thiết kế chi tiết: [design/data-generator.md](../design/data-generator.md) (Phần 2).

`stream.py` **chỉ UPDATE `unit_cost` / `unit_price`** của product có sẵn. Không insert, không xóa,
không đụng bảng khác, không tự set `updated_at` (trigger trong DB lo việc đó).

## Chạy

```bash
make stream                       # 1 cycle rồi thoát (mặc định)
make stream-loop                  # chạy liên tục, Ctrl+C để dừng
uv run stream --seed 42           # tái lập được lựa chọn và giá trị
uv run stream --help              # xem mọi tham số và mặc định
```

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--products` | 5 | Số product đổi mỗi cycle |
| `--cost-pct-min` / `--cost-pct-max` | 0.01 / 0.05 | Biên độ đổi giá vốn (tăng hoặc giảm) |
| `--price-probability` | 0.10 | Xác suất một product được chọn đổi thêm giá bán |
| `--price-pct-min` / `--price-pct-max` | 0.01 / 0.08 | Biên độ đổi giá bán |
| `--cooldown-hours` | 24 | Bỏ qua product vừa đổi trong N giờ, 0 = tắt |
| `--loop` / `--interval` | tắt / 30 giây | Chạy liên tục |
| `--seed` | không | Random seed |

Mỗi cycle là một transaction DB: thành công hết hoặc rollback hết. Lỗi kết nối/constraint
trả exit code khác 0; bảng `product` trống thì báo "chạy `make seed` trước".

Ví dụ log:

```text
[cycle 1] product 13 SKU-00013: cost 108300 -> 110400, price 162000 -> 162000 (supplier_cost_adjustment)
[cycle 1] product 326 SKU-00326: cost 32100 -> 30800, price 46000 -> 44000 (price_revision)
[cycle 1] scanned 500, planned 5, updated 5 products
```

## Kết nối với các phase khác

```text
make stream  ->  product.updated_at mới  ->  uv run ingest (merge theo id)  ->  dbt snapshot (phase 5)
```

`--cooldown-hours` đảm bảo một product không bị đổi nhiều lần giữa hai lần ingest + snapshot,
vì snapshot chỉ thấy trạng thái cuối cùng tại lúc chạy.

## Kiểm tra

```sql
SELECT id, product_sku, unit_cost, unit_price, updated_at
FROM retail.product ORDER BY updated_at DESC LIMIT 10;
```

Test tự động: `tests/test_stream.py` (xem [Testing](../design/data-generator.md#testing)).
