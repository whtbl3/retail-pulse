# Phase 4 — Mô phỏng thay đổi nguồn (`stream.py`)

Mục tiêu: tạo thay đổi nhỏ, thực tế trên bảng `product` (giá) và `employee` (chuyển cửa hàng) để dlt load
incremental (append) và sau này dbt dựng lịch sử từ các phiên bản trong RAW.
Thiết kế chi tiết: [design/data-generator.md](../design/data-generator.md) (Phần 2).

Mặc định `stream.py` **chỉ UPDATE** `unit_cost` / `unit_price` của product có sẵn và `store_id` của employee
đang làm việc (`end_date` null). Không insert, không xóa, không đụng bảng khác, không tự set `updated_at` (trigger trong DB lo việc đó).
Với `--sales N` (hoặc `make stream-sales`), mỗi cycle còn **INSERT thêm N giao dịch bán hàng mới** (xem "Bán thêm" bên dưới); khi đó mới có insert vào `sales_transaction` và `sales_transaction_item`.

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
| `--sales` | 0 (tắt) | Số giao dịch bán hàng mới INSERT mỗi cycle |
| `--transfers` | 1 | Số employee chuyển cửa hàng mỗi cycle (luôn sang cửa hàng khác), 0 = tắt |
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

## Bán thêm (`--sales N`)

```bash
make stream-sales             # 1 cycle: đổi giá, chuyển nhân viên, và bán thêm SALES=300 giao dịch
make stream-sales SALES=50
uv run stream --sales 100 --products 3
```

Mục đích: có **giao dịch mới thật** ở nguồn để thử cả chuỗi dlt, dbt và phần incremental của `fct_sales`
(`stream` thuần chỉ đổi dữ liệu có sẵn nên không thêm dòng nào vào fact).

Cách sinh, dùng lại đúng luật bán hàng của `seed.py` (`TransactionGenerator`, gồm giảm giá khuyến mãi
theo đơn vị, coupon theo dòng, tỉ lệ trạng thái 95% completed, 2% cancelled, 3% returned):
1. **Khoảng thời gian:** từ mốc muộn nhất của `sales_transaction` (lấy lớn hơn của `transaction_ts` và
   `updated_at`) đến bây giờ. Mốc bắt đầu phải **sau** mốc nạp của dlt (con trỏ `updated_at`), nếu
   không giao dịch mới sẽ không bao giờ được nạp.
2. **Giờ mở cửa:** chỉ lấy phần nằm trong 7h–22h (giờ `Asia/Ho_Chi_Minh`); thời gian đóng cửa bị bỏ qua.
   Các thời điểm phân bố đều trên tổng thời gian mở cửa đó.
3. **Cửa hàng và nhân viên:** cửa hàng ngẫu nhiên có nhân viên đang làm hôm đó; nhân viên là người của
   cửa hàng **hiện tại** (kể cả sau khi `stream` chuyển cửa hàng).
4. **Giá:** `regular_price` là giá bán hiện tại của product. Bán xảy ra **trước** khi đổi giá trong cùng
   cycle, nên đổi giá chỉ có hiệu lực cho giao dịch sau.
5. Ghi một transaction DB cho cả lô (giao dịch và dòng chi tiết).

Nếu chưa có giờ mở cửa nào trôi qua kể từ giao dịch gần nhất (ví dụ chạy lần thứ hai ngay trong đêm),
lệnh ghi log "chưa có giờ mở cửa nào..." và không bán gì. Số giao dịch mỗi cycle cố định theo `--sales`,
không phụ thuộc độ dài khoảng thời gian; khác `seed.py`, các thời điểm không dồn về chiều tối.

## Kết nối với các phase khác

```text
make stream  ->  product.updated_at mới  ->  uv run ingest (append)  ->  dbt SCD2 (phase 5)
```

**Hạn chế:** con trỏ `updated_at` chỉ thấy trạng thái cuối của một dòng tại lúc ingest, nên mỗi cycle
`stream.py` phải được ingest trước khi chạy cycle kế tiếp (nếu không, phiên bản trung gian bị mất).
Nguồn cũng không có DELETE vì con trỏ không thấy dòng bị xóa.

## Kiểm tra

```sql
SELECT id, product_sku, unit_cost, unit_price, updated_at
FROM retail.product ORDER BY updated_at DESC LIMIT 10;
```

Test tự động: `tests/test_stream.py` (xem [Testing](../design/data-generator.md#testing)).
