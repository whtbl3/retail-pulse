# Phase 4 — Mô phỏng thay đổi nguồn (`stream.py`)

Dữ liệu thật không đứng yên: giá đổi, nhân viên chuyển cửa hàng, hóa đơn mới đổ về liên tục. Nếu nguồn chỉ có
một bộ dữ liệu tĩnh thì không kiểm tra được hai thứ quan trọng nhất của dự án: **SCD2** (lịch sử đổi giá, đổi cửa hàng) và
**incremental** (chỉ nạp phần mới). `stream.py` tạo ra những thay đổi nhỏ, thực tế đó.
Thiết kế chi tiết: [design/data-generator.md](../design/data-generator.md) (Phần 2).

Mặc định `stream.py` **chỉ UPDATE**: `unit_cost` và `unit_price` của product có sẵn, `store_id` của employee đang làm
việc (`end_date` rỗng). Không INSERT, không DELETE, không tự set `updated_at` (trigger trong DB làm việc đó).
Thêm `--sales N` thì mỗi cycle còn **INSERT N giao dịch bán mới** (mục "Bán thêm").

## Chạy

```bash
make stream                       # 1 cycle rồi thoát
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
| `--sales` | 0 (tắt) | Số giao dịch bán mới INSERT mỗi cycle |
| `--transfers` | 1 | Số employee chuyển cửa hàng mỗi cycle (luôn sang cửa hàng khác), 0 = tắt |
| `--loop` / `--interval` | tắt / 30 giây | Chạy liên tục |
| `--seed` | không | Random seed |

Mỗi cycle là một transaction DB: thành công hết hoặc rollback hết. Lỗi kết nối hoặc ràng buộc trả mã thoát khác 0;
bảng `product` trống thì báo "chạy `make seed` trước".

```text
[cycle 1] product 13 SKU-00013: cost 108300 -> 110400, price 162000 -> 162000 (supplier_cost_adjustment)
[cycle 1] product 326 SKU-00326: cost 32100 -> 30800, price 46000 -> 44000 (price_revision)
[cycle 1] scanned 500, planned 5, updated 5 products
```

## Bán thêm (`--sales N`)

```bash
make stream-sales             # 1 cycle: đổi giá, chuyển nhân viên, bán thêm SALES=300 giao dịch
make stream-sales SALES=50
uv run stream --sales 100 --products 3
```

*Vì sao cần:* `stream` thuần chỉ đổi dữ liệu có sẵn nên không thêm dòng nào vào fact. Muốn thử cả chuỗi dlt, dbt và
phần incremental của `fct_sales` thì phải có **giao dịch mới thật** ở nguồn.

Cách sinh dùng lại đúng luật bán hàng của `seed.py` (khuyến mãi theo đơn vị, coupon theo dòng, 95% completed, 2%
cancelled, 3% returned):
1. **Khoảng thời gian:** từ mốc muộn nhất của `sales_transaction` (lớn hơn của `transaction_ts` và `updated_at`) đến
   bây giờ. Mốc bắt đầu phải **sau** mốc nạp của dlt; nếu không, giao dịch mới sẽ không bao giờ được nạp.
2. **Giờ mở cửa:** chỉ lấy phần nằm trong 7h–22h (giờ `Asia/Ho_Chi_Minh`), thời gian đóng cửa bị bỏ qua.
3. **Cửa hàng và nhân viên:** cửa hàng ngẫu nhiên có nhân viên đang làm; nhân viên thuộc cửa hàng **hiện tại**
   (kể cả sau khi `stream` vừa chuyển cửa hàng).
4. **Giá:** `regular_price` là giá bán hiện tại. Bán xảy ra **trước** khi đổi giá trong cùng cycle, nên đổi giá chỉ có
   hiệu lực cho giao dịch sau.
5. Ghi cả lô trong một transaction DB.

Nếu chưa có giờ mở cửa nào trôi qua kể từ giao dịch gần nhất (ví dụ chạy lần hai ngay trong đêm), lệnh ghi log
"chưa có giờ mở cửa nào..." và không bán gì. Số giao dịch mỗi cycle cố định theo `--sales`, các thời điểm không dồn
về chiều tối như `seed.py`.

## Hạn chế: phải ingest sau mỗi cycle

```text
make stream  ->  product.updated_at mới  ->  make ingest (append)  ->  dbt SCD2 (phase 5)
```

Con trỏ `updated_at` chỉ thấy **trạng thái cuối** của một dòng tại lúc ingest. Vì vậy mỗi cycle phải được ingest
trước khi chạy cycle kế tiếp. *Nếu bỏ qua:* hai lần đổi giá liên tiếp chỉ để lại một phiên bản trong RAW, phiên bản
trung gian mất vĩnh viễn và SCD2 thiếu một đoạn lịch sử. Nguồn cũng không có DELETE vì con trỏ không thấy dòng đã xóa.

## Kiểm tra

```sql
SELECT id, product_sku, unit_cost, unit_price, updated_at
FROM retail.product ORDER BY updated_at DESC LIMIT 10;
```

Test tự động: `tests/test_stream.py` (xem [Testing](../design/data-generator.md#testing)).

## Đọc thêm

- [Kimball: SCD Type 2](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/):
  vì sao lưu mỗi lần thay đổi thành một dòng mới.

Tiếp theo: [Phase 5 — dbt](05-dbt.md).
