# Phase 2 — Seed dữ liệu lịch sử (`seed.py`)

Mục tiêu: nạp một bộ dữ liệu nền thực tế và tái lập được (cùng `--seed` thì cùng dữ liệu).
Thiết kế chi tiết: [design/data-generator.md](../design/data-generator.md) (Phần 1).

## Chạy

```bash
make seed                          # 365 ngày, ~100k giao dịch
make seed DAYS=90 ROWS=20000       # nhỏ hơn để thử nhanh
make reseed                        # TRUNCATE toàn bộ rồi seed lại
uv run seed --help                 # xem mọi tham số
```

`seed` từ chối chạy nếu database đã có dữ liệu, trừ khi có `--reset` (`make reseed`).

## Kết quả mặc định

| Bảng | Số dòng |
|---|---|
| `store` | 10 |
| `employee` | 80 (8 / cửa hàng, có người vào/nghỉ giữa kỳ) |
| `category` / `brand` / `payment_method` | 10 / 30 / 4 |
| `product` | 500 (`product_name` luôn bắt đầu bằng tên brand của nó) |
| `promotion` | 40, mỗi chương trình áp cho 5–20 sản phẩm |
| `sales_transaction` | ~100.000, rải trong 365 ngày tới hôm qua |
| `sales_transaction_item` | ~2,8 dòng mỗi giao dịch |

Luật sinh dữ liệu chính: cuối tuần đông hơn 1,4 lần, giờ bán 7h–22h (đông nhất buổi tối),
nhân viên chỉ bán ở cửa hàng của mình và trong thời gian đang làm việc, promotion chỉ áp khi
còn hiệu lực, `regular_price` là giá tại thời điểm bán.

## Kiểm tra

```sql
SELECT count(*) FROM retail.sales_transaction;
SELECT min(transaction_ts), max(transaction_ts) FROM retail.sales_transaction;
```

Test tự động: `tests/test_seed.py` (xem [Testing](../design/data-generator.md#testing)).

Tiếp theo: [Phase 3 — Ingestion sang Snowflake](03-ingestion-snowflake.md).
