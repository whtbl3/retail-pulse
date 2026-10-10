# Mô hình dữ liệu phân tích (Kimball)

Một hóa đơn siêu thị có ba dòng hàng. Khi dựng warehouse, câu hỏi đầu tiên không phải "dùng công cụ nào" mà là: **một dòng
trong bảng fact sẽ đại diện cho cái gì?** Một hóa đơn? Một dòng hàng? Một ngày bán? Trả lời sai câu này thì mọi thứ phía sau
đều lệch. Bài này đi theo quy trình thiết kế bốn bước của Kimball (mở rộng thành sáu), dựa trên nguồn đã mô tả ở
[operational-data-modeling.md](operational-data-modeling.md). Bản triển khai thật nằm ở [phase 5](../phases/05-dbt.md).

| Bước | Nội dung |
|---|---|
| 1 | Xác định quy trình nghiệp vụ |
| 2 | Chốt grain (một dòng fact là gì) |
| 3 | Xác định các dimension |
| 4 | Xác định các fact (số đo) |
| 5 | Chọn kiểu dimension (Type 0, 1, 2) |
| 6 | Chọn kiểu bảng fact |

Đọc thêm: [Four-Step Dimensional Design Process](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/four-4-step-design-process/).

## Bước 1. Quy trình nghiệp vụ

**Bán hàng tại quầy thu ngân (POS).** Đây là sự kiện `Buy` trong mô hình conceptual, và là nguồn duy nhất mang đủ giá, số lượng,
khuyến mãi, cửa hàng, thu ngân, phương thức thanh toán và thời điểm cùng lúc.

Những câu hỏi quy trình này phải trả lời được (từ bài toán trong README):
- doanh thu và xu hướng theo thời gian;
- hiệu quả theo sản phẩm, danh mục, nhãn hàng;
- hiệu quả theo cửa hàng (và thu ngân);
- hiệu quả khuyến mãi;
- lợi nhuận gộp theo thời gian, dùng **giá vốn đúng tại thời điểm bán**.

Khuyến mãi **không phải** một quy trình riêng: ở nguồn, khuyến mãi là bối cảnh của một dòng hàng (một dimension gắn vào fact),
không phải sự kiện có thời điểm và số đo riêng. Mô hình "độ phủ khuyến mãi" (factless fact từ `promotion_product` × ngày) có thể
thêm sau khi fact chính chạy được.

Ngoài phạm vi: tồn kho (`Stocks`), trả hàng và hủy đơn (chỉ phân tích giao dịch `completed`, xem mục 7.3 của Project-Spec).

Đọc thêm: [Business Processes](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/business-process/).

## Bước 2. Grain

**Một dòng fact là một dòng hàng trên hóa đơn, tức một `sales_transaction_item` (`transaction_id`, `line_number`), chỉ giao dịch
`completed`.**

*Vì sao chọn mức này:* đây là mức chi tiết nhỏ nhất ở nguồn, nên mọi câu hỏi ở bước 1 đều cộng dồn được từ nó mà không mất thông
tin. Chọn grain thô hơn (một hóa đơn một dòng) thì không còn trả lời được "sản phẩm nào bán chạy". Hệ quả:

- `transaction_id` nằm thẳng trong fact như một **degenerate dimension**. Số liệu cấp hóa đơn (giá trị giỏ hàng, giá trị hóa đơn
  trung bình) lấy từ một bảng tổng hợp xây trên fact này, không đổi grain.
- Thuộc tính của hóa đơn (cửa hàng, thu ngân, thanh toán, thời điểm) lặp lại trên mọi dòng của cùng hóa đơn, nên **đếm hóa đơn
  phải dùng `COUNT(DISTINCT transaction_id)`**. *Nếu dùng `COUNT(*)` thì đếm dòng hàng, không phải hóa đơn.*
- Nguồn lưu `regular_price` tại thời điểm bán trên dòng hàng, nhưng **không lưu giá vốn**. Giá vốn chỉ có ở `product.unit_cost` và
  nó đổi theo thời gian. Muốn lợi nhuận đúng phải lấy phiên bản `product` hợp lệ tại thời điểm bán (quyết định ở bước 3 và 5).

**Trạng thái giao dịch (đã chốt):** fact chỉ chứa `completed`, không có cột status, không phân tích trả hàng. Một hóa đơn đổi trạng
thái sau khi đã nạp (ví dụ `completed` sang `returned`) nằm ngoài phạm vi: hóa đơn được coi là không đổi sau khi ghi.

Đọc thêm: [Grain](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/),
[Degenerate Dimensions](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/degenerate-dimension/).

## Bước 3. Dimension

Mỗi dimension trả lời một trong "ai, cái gì, ở đâu, khi nào, bằng cách nào" cho một dòng hàng. Với grain ở bước 2 có **7 dimension và 2
degenerate dimension**.

| Dimension | Trả lời | Nguồn | Thuộc tính chính |
|---|---|---|---|
| `dim_date` | Ngày nào | sinh từ lịch, không có ở nguồn | ngày, năm, quý, tháng, tuần, thứ, cờ cuối tuần |
| `dim_time` | Giờ nào | sinh sẵn, 1.440 dòng (mỗi phút một dòng) | giờ, phút, AM/PM, buổi (`Morning`, `Afternoon`, `Evening`, `Night`) |
| `dim_product` | Bán cái gì | `product` + `category` + `brand` | SKU, tên, danh mục, nhãn hàng, giá, giá vốn |
| `dim_store` | Ở đâu | `store` (qua `sales_transaction.store_id`) | tên cửa hàng, địa chỉ, số điện thoại |
| `dim_employee` | Thu ngân nào | `employee` | tên, cửa hàng hiện tại, ngày vào, ngày nghỉ |
| `dim_payment_method` | Thanh toán thế nào | `payment_method` | tên phương thức |
| `dim_promotion` | Khuyến mãi nào | `promotion` | loại (phần trăm hoặc số tiền cố định), giá trị, ngày bắt đầu, ngày kết thúc, nhãn hiển thị |

Degenerate dimension (nằm thẳng trong fact, không có bảng riêng): `transaction_id` và `line_number`.

Những điểm rút ra từ nguồn:

- **Danh mục và nhãn hàng gộp vào `dim_product`** (star schema, không phải snowflake). Nguồn tách chúng ra chỉ để đạt 3NF; mô hình
  phân tích không cần.
- **Cửa hàng của hóa đơn khác cửa hàng của nhân viên.** `sales_transaction.store_id` là nơi giao dịch xảy ra; `employee.store_id` là nơi nhân viên
  đang làm và có thể đổi. Fact giữ khóa `dim_store` của hóa đơn; cửa hàng của nhân viên chỉ là thuộc tính của `dim_employee`.
- **`dim_product` giữ giá và giá vốn** vì chúng đổi theo thời gian, và đó chính là lý do cần lịch sử (bước 2).
- **Không có dimension cho trạng thái giao dịch**, vì fact chỉ chứa `completed`.
- **`dim_promotion` không có tên** vì nguồn không có cột tên, nên nhãn hiển thị được sinh từ loại và giá trị: `15% off`, `10,000 VND off`
  (nhãn dùng tiếng Anh cho toàn dashboard).

**Các quyết định đã chốt:**

1. **Thêm `dim_time` và giữ `transaction_ts` trong fact.** Giờ bán trải từ 07:00 đến 21:00 với đỉnh quanh 18:00, nên phân tích theo buổi có ý
   nghĩa. Ngày và giờ là hai dimension nhỏ thay vì một dimension mỗi phút của cả năm. `transaction_ts` phải ở lại fact vì join sang lịch
   sử `dim_product` cần giờ chính xác, `date_key` và `time_key` không thay thế được.
2. **Giữ dữ liệu cá nhân trong `dim_employee`** (`salary`, `address`) để dùng cho bài tập bảo mật dữ liệu sau này, gắn `meta: {pii: true}`
   trong YAML để áp chính sách che dữ liệu theo tag. (Ngày sinh và số điện thoại không được đưa vào vì dashboard không dùng.)
3. **Dòng hàng không có khuyến mãi dùng thành viên cố định `-1` "No promotion"**, để khóa trong fact không bao giờ rỗng. Thêm thành viên
   `-2` "Unknown" cho khóa chưa có trong dimension (dữ liệu đến trễ); quy ước `-2` áp cho mọi dimension.

Lưu ý chuyển sang bước 5: `salary` đổi thường xuyên. Nếu nó là cột được theo dõi thì mỗi lần tăng lương tạo một phiên bản nhân viên mới. Chỉ
`store_id` được theo dõi, `salary` bị ghi đè.

## Bước 4. Fact

Bảng fact là `fct_sales`, mỗi dòng một dòng hàng `completed`. Mọi số đo tiền và số lượng đều **cộng dồn được**, trừ hai đơn giá `regular_price`
và `unit_cost`. Các tỷ lệ (biên lợi nhuận gộp, giá trị hóa đơn trung bình) **không lưu trong fact**: chúng được định nghĩa thành metric trong
Preset, ví dụ `SUM(gross_profit) / SUM(net_amount)`, để không ai vô tình lấy trung bình của các tỷ lệ.

**Khóa và thuộc tính trong fact:** `date_key`, `time_key`, `product_key`, `store_key`, `employee_key`, `payment_method_key`, `promotion_key`,
`transaction_id`, `line_number`, `transaction_ts`.

**Số đo:**

| Số đo | Cách có được | Cộng dồn được |
|---|---|---|
| `quantity` | nguồn | có |
| `regular_price` | nguồn (giá tại thời điểm bán) | không, là đơn giá |
| `unit_cost` | giá vốn của phiên bản sản phẩm hợp lệ tại `transaction_ts` | không, là đơn giá |
| `gross_amount` | `quantity × regular_price` | có |
| `discount_amount` | giảm giá khuyến mãi, công thức bên dưới | có |
| `coupon_amount` | nguồn | có |
| `net_amount` | `gross_amount − discount_amount − coupon_amount` | có |
| `cost_amount` | `quantity × unit_cost` | có |
| `gross_profit` | `net_amount − cost_amount` | có |

### Tính cộng dồn của số đo

| Loại | Nghĩa | Trong `fct_sales` |
|---|---|---|
| **Additive** | cộng được qua mọi dimension, kể cả thời gian | `quantity`, `gross_amount`, `discount_amount`, `coupon_amount`, `net_amount`, `cost_amount`, `gross_profit` |
| **Semi-additive** | cộng được qua mọi dimension trừ thời gian (ví dụ số dư tồn kho: cộng các cửa hàng được, cộng các ngày thì không) | không có |
| **Non-additive** | không cộng được qua dimension nào | `regular_price`, `unit_cost` (đơn giá); các tỷ lệ cũng không cộng được nhưng là metric trong Preset, không phải cột của fact |

Không có số đo semi-additive là có chủ ý: loại này gần như chỉ xuất hiện ở fact dạng periodic snapshot, mà mô hình này không có (tồn kho nằm
ngoài phạm vi, xem bước 6). `fct_sales` là transaction fact nên mọi số đo tiền và số lượng đều cộng dồn hoàn toàn.

Đọc thêm: [Additive, Semi-Additive, and Non-Additive Facts](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/additive-semi-additive-non-additive-fact/).

### Quy ước về khuyến mãi và coupon

Nguồn không lưu số tiền giảm của khuyến mãi (một dòng chỉ có `promotion_id`) và không nói áp theo đơn vị hay theo dòng, nên quy ước được chốt ở đây:

- **Khuyến mãi áp theo đơn vị**, nhân với số lượng:
  - phần trăm: `discount_amount = quantity × regular_price × amount / 100`
  - số tiền cố định: `discount_amount = quantity × MIN(amount, regular_price)`

  `MIN` chặn giá sau giảm không âm. Khớp với seed: khuyến mãi cố định chỉ gán cho sản phẩm có `unit_price >= amount × 4`, nên mức giảm luôn
  nhỏ hơn giá một đơn vị.
- **`coupon_amount` áp theo dòng**, không nhân số lượng. Seed gán nó một lần cho cả dòng.
- Khi sửa `seed.py` hoặc `stream.py`, phải giữ cả hai quy ước.

### Giá vốn được ghi vào fact lúc nạp

`unit_cost` và `cost_amount` được ghi vào fact lúc nạp. `unit_cost` phải lấy từ **phiên bản `dim_product` hợp lệ tại `transaction_ts`** (range join,
bước 5), không phải từ sản phẩm hiện tại ở tầng silver. *Nếu dùng bảng hiện tại:* lúc nạp thì đúng, nhưng một lần full refresh sẽ tính lại cả lịch
sử bằng giá vốn mới, đúng cái lỗi mà SCD2 sinh ra để tránh.

Vì sao lưu vào fact:
- Truy vấn trong Preset đơn giản: lợi nhuận gộp là một phép `SUM` trên fact, không phải join theo khoảng thời gian mỗi lần mở dashboard.
- Số đã báo cáo ổn định; một hóa đơn chỉ được tính lại khi nạp lại.
- Vẫn truy vết được: `product_key` trỏ đúng phiên bản sản phẩm nên đối chiếu `unit_cost` bằng một phép join.

Giới hạn đã biết: nếu nguồn sửa một giá vốn trong quá khứ, fact không tự cập nhật trừ khi chạy full refresh. Chấp nhận được cho dự án portfolio.

**Test dbt:** `net_amount >= 0` và `discount_amount <= gross_amount`, bắt trường hợp generator hoặc stream vi phạm quy ước khuyến mãi.

## Bước 5. Kiểu dimension (SCD)

| Dimension | Kiểu | Lý do |
|---|---|---|
| `dim_date` | Type 0 | sinh từ lịch, không bao giờ đổi |
| `dim_time` | Type 0 | sinh sẵn 1.440 phút, không bao giờ đổi |
| `dim_product` | **Type 2** | giá vốn và giá đổi theo thời gian, cần cho lợi nhuận gộp tại thời điểm bán |
| `dim_employee` | **Type 2** | cửa hàng của nhân viên đổi, cần biết họ làm ở đâu lúc bán |
| `dim_store` | Type 1 | `stream.py` không đổi cửa hàng; ghi đè nếu nguồn sửa |
| `dim_payment_method` | Type 1 | danh mục nhỏ, ghi đè |
| `dim_promotion` | Type 1 | chương trình có ngày bắt đầu và kết thúc cố định; ghi đè nếu nguồn sửa (hóa đơn cũ không đổi, xem bên dưới) |

Mọi dimension có thành viên `-2` "Unknown"; `dim_promotion` còn có `-1` "No promotion" (bước 3).

Đọc thêm: [Type 2: Add New Row](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/),
[Dimension Surrogate Keys](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/dimension-surrogate-key/).

### Cột nào tạo phiên bản mới (Type 2)

- **`dim_product`:** `unit_cost`, `unit_price`, `category_id`, `brand_id`. Tên sản phẩm bị ghi đè (Type 1) vì thường chỉ đổi khi sửa lỗi chính tả.
  Nguồn hiện không đổi danh mục hay nhãn hàng nên theo dõi hai cột này không tạo thêm phiên bản; nếu sau này sản phẩm đổi danh mục, doanh thu
  theo danh mục trong quá khứ vẫn đúng. Danh sách cột theo dõi dễ đổi: lịch sử nằm ở RAW, chỉ cần sửa code rồi chạy dbt full refresh.
- **`dim_employee`:** chỉ `store_id`. `salary` và các cột khác bị ghi đè (Type 1) bằng giá trị mới nhất vì lương đổi thường xuyên, mỗi lần
  tăng lương tạo một phiên bản thừa. Cột cá nhân gắn `meta: {pii: true}` (bước 3).

### Dựng phiên bản từ RAW

Ingestion ghi mỗi dòng `product` hoặc `employee` đã đổi thành một dòng mới ở RAW (cùng `id`, `updated_at` mới hơn; xem mục 9.2 của
Project-Spec). SCD2 được dựng thẳng từ các dòng đó bằng window function, **không dùng `dbt snapshot`**: RAW đã giữ mọi phiên bản, snapshot chỉ thêm
một bản sao lịch sử không dựng lại được, còn window function có tính **idempotent** (`dbt build --full-refresh` ra cùng kết quả bao nhiêu lần
cũng được). Hai cách có cùng mức chi tiết.

0. **Staging dedup trước.** Con trỏ incremental có thể nạp lại các dòng nằm đúng biên, nên staging giữ một dòng cho mỗi tổ hợp (`id`, `updated_at`,
   cùng mọi cột nghiệp vụ): `qualify row_number() over (partition by <mọi cột nghiệp vụ> order by _dlt_load_id desc) = 1`.
1. Sắp xếp các dòng của một khóa nghiệp vụ theo `updated_at`.
2. **So từng dòng với dòng trước bằng `LAG` và `IS DISTINCT FROM`**, chỉ giữ dòng có cột theo dõi thay đổi. Không dùng `DISTINCT` hay gom theo giá
   trị: chuỗi giá A → B → A phải ra 3 phiên bản; gom theo giá trị sẽ gộp hai A làm một và khoảng hiệu lực sai. `IS DISTINCT FROM` cũng xử lý đúng `NULL`.
3. `valid_from` là `updated_at` của dòng đó; `valid_to` là `valid_from` của phiên bản kế. Phiên bản cuối có `valid_to = '9999-12-31'` và `is_current = true`.
4. **Phiên bản đầu của mỗi khóa có `valid_from = '1900-01-01'`.** Dòng đầu tiên ở RAW chỉ xuất hiện ở lần nạp đầu, sau toàn bộ giao dịch lịch sử
   của seed; dùng `updated_at` thật thì 100.000 đơn seed không khớp phiên bản nào.
5. **Cột Type 1 phải lấy giá trị mới nhất của khóa.** Sau bước 2, các cột như `salary` hay `product_name` vẫn mang giá trị tại thời điểm của phiên
   bản đó, thành "SCD2 thiếu". Dùng `FIRST_VALUE(...) over (partition by id order by updated_at desc)` để ghi đè giá trị mới nhất lên mọi phiên bản.

Mã thật của `int_product_scd2` (rút gọn còn hai cột theo dõi thay vì bốn):

```sql
WITH versions AS (
    SELECT
        product_id,
        FIRST_VALUE(product_name) OVER (PARTITION BY product_id ORDER BY updated_at DESC) AS product_name,  -- Type 1
        unit_price, unit_cost, updated_at,                                                                   -- Type 2
        LAG(unit_price) OVER (PARTITION BY product_id ORDER BY updated_at) AS prev_unit_price,
        LAG(unit_cost)  OVER (PARTITION BY product_id ORDER BY updated_at) AS prev_unit_cost,
        LAG(updated_at) OVER (PARTITION BY product_id ORDER BY updated_at) AS prev_updated_at
    FROM {{ ref('stg_product') }}
),
change_points AS (
    SELECT * FROM versions
    WHERE prev_updated_at IS NULL                       -- phiên bản đầu
       OR prev_unit_price IS DISTINCT FROM unit_price
       OR prev_unit_cost  IS DISTINCT FROM unit_cost
)
SELECT
    product_id, product_name, unit_price, unit_cost,
    IFF(prev_updated_at IS NULL, '1900-01-01'::timestamp, updated_at)                  AS valid_from,
    COALESCE(LEAD(updated_at) OVER (PARTITION BY product_id ORDER BY updated_at),
             '9999-12-31'::timestamp)                                                  AS valid_to,
    LEAD(updated_at) OVER (PARTITION BY product_id ORDER BY updated_at) IS NULL        AS is_current
FROM change_points
```

Khóa thay thế của dimension là hash của khóa nghiệp vụ và `valid_from` của phiên bản (macro `surrogate_key`, dùng hàm `HASH` của Snowflake nên là
số nguyên 64 bit). Quy ước biên: `valid_from <= transaction_ts < valid_to`.

Hệ quả:
- **RAW là nơi duy nhất giữ lịch sử.** Không bao giờ chạy dlt với `refresh="drop_sources"`, `drop_resources` hay `replace` trên `product` và `employee`:
  toàn bộ lịch sử SCD2 sẽ mất.
- **`dim_promotion` là Type 1:** `discount_amount` được tính và ghi vào fact lúc nạp, giống `unit_cost`, nên sửa khuyến mãi không đổi hóa đơn cũ; chúng
  chỉ đổi khi full refresh (cùng giới hạn như bước 4).

### Join fact với một phiên bản

`fct_sales` join `dim_product` và `dim_employee` theo khóa nghiệp vụ (`product_id`, `employee_id`) và khoảng `valid_from <= transaction_ts < valid_to`.
Fact giữ `product_key` và `employee_key` trỏ đúng phiên bản.

Giới hạn (cũng ở mục 9.2 của Project-Spec): mỗi cycle `stream.py` phải được ingest trước cycle kế tiếp, nếu không các phiên bản trung gian mất.

## Bước 6. Kiểu bảng fact

| Kiểu | Dùng cho | Áp dụng ở đây |
|---|---|---|
| **Transaction fact** | mỗi dòng là một sự kiện xảy ra tại một thời điểm | **`fct_sales`** |
| Periodic snapshot | trạng thái theo chu kỳ (ví dụ tồn kho cuối ngày) | không dùng, tồn kho ngoài phạm vi |
| Accumulating snapshot | một quy trình nhiều cột mốc, dòng được cập nhật khi qua từng mốc (đặt hàng → giao hàng → thanh toán) | không dùng, nguồn không có vòng đời nhiều mốc |
| Factless fact | ghi một quan hệ, không có số đo | để sau: độ phủ khuyến mãi |

**`fct_sales` là transaction fact.** Mỗi dòng hàng là một sự kiện bán tại `transaction_ts`, được tạo một lần và không đổi về sau. Đặc điểm:
- grain nguyên tử (bước 2), số đo cộng dồn (bước 4), dày đặc: mọi dòng có đủ số đo;
- nạp incremental theo (`transaction_id`, `line_number`); hóa đơn không đổi sau khi ghi nên không cần xử lý xóa hay cập nhật;
- mỗi dòng gắn với thời gian qua `date_key` và `time_key`, và giữ `transaction_ts` để join các phiên bản SCD2 (bước 5). `date_key` và `time_key`
  tính từ giờ địa phương (`Asia/Ho_Chi_Minh`) chứ không phải UTC.

Các fact khác, xây từ cùng nguồn, làm sau khi `fct_sales` chạy ổn:
- **`fct_sales_transaction`** (bảng tổng hợp, mỗi dòng một hóa đơn): giá trị giỏ hàng và giá trị hóa đơn trung bình. Xây từ `fct_sales`, không đổi grain.
- **Độ phủ khuyến mãi** (factless fact): sản phẩm nào đang khuyến mãi mà không bán được. Xây từ `promotion_product` × `dim_date` giữa `start_date` và `end_date`.

Hai fact bổ sung này nằm trong tài liệu cho đến khi cần dùng; chưa có trong mục 10.2 của Project-Spec.

Đọc thêm: [Transaction Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/transaction-fact-table/),
[Periodic Snapshot](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/periodic-snapshot-fact-table/),
[Accumulating Snapshot](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/accumulating-snapshot-fact-table/),
[Factless Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/factless-fact-table/).
