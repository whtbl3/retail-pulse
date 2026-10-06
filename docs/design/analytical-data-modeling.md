# Analytical Data Modeling

Mô hình phân tích (Kimball) cho warehouse, xây từ nguồn đã mô tả ở
[operational-data-modeling.md](operational-data-modeling.md). Làm theo từng bước, mỗi bước được
duyệt rồi mới sang bước kế.

| Bước | Nội dung | Trạng thái |
|---|---|---|
| 1 | Identify the business process | Đã duyệt |
| 2 | Clarify the grain | Đã duyệt |
| 3 | Identify the dimensions | Đã duyệt |
| 4 | Identify the facts | Đã duyệt |
| 5 | Xác định loại dimension (Type 0/1/2...) | Đã duyệt |
| 6 | Xác định loại bảng fact (transaction / periodic snapshot / accumulating) | Đã duyệt |

## Bước 1. Business process

**Bán hàng tại quầy POS (checkout).** Đây là sự kiện `Buy` trong conceptual model, là nguồn
duy nhất có đủ giá, số lượng, khuyến mãi, cửa hàng, thu ngân, phương thức thanh toán và thời điểm.

Câu hỏi kinh doanh quy trình này phải trả lời (từ bài toán ở README):

- doanh thu và xu hướng theo thời gian;
- hiệu quả theo sản phẩm, danh mục, thương hiệu;
- hiệu quả theo cửa hàng (và thu ngân);
- hiệu quả khuyến mãi;
- lợi nhuận gộp theo thời gian, dùng giá vốn đúng tại thời điểm bán.

Khuyến mãi không tách thành process riêng: trong nguồn nó là ngữ cảnh của dòng hàng (sẽ là một dimension gắn vào fact), không phải sự kiện có thời điểm và số đo riêng. Mô hình "promotion coverage" (factless fact, dựng từ `promotion_product` × ngày) có thể thêm sau khi fact chính chạy ổn.

Không thuộc quy trình này (ngoài phạm vi): tồn kho (`Stocks`), đổi trả và hủy giao dịch (chỉ phân
tích giao dịch `completed`, xem Project-Spec mục 7.3).

## Bước 2. Grain

**Một dòng cho mỗi dòng hàng của hóa đơn, tức mỗi `sales_transaction_item`
(`transaction_id`, `line_number`), chỉ giao dịch `completed`.**

Lý do: đây là mức chi tiết nhỏ nhất của nguồn, nên mọi câu hỏi ở bước 1 đều tổng hợp được từ đó mà
không mất thông tin. Hệ quả cần biết:

- `transaction_id` nằm trong fact dưới dạng degenerate dimension; chỉ số theo hóa đơn (basket size, giá trị trung bình mỗi đơn) làm bằng một mart tổng hợp từ fact này, không đổi grain;
- thuộc tính của hóa đơn (cửa hàng, thu ngân, phương thức thanh toán, thời điểm) lặp lại trên mọi
  dòng hàng của cùng hóa đơn; số hóa đơn phải đếm bằng `COUNT(DISTINCT transaction_id)`;
- nguồn lưu `regular_price` tại thời điểm bán trên dòng hàng, nhưng **không lưu giá vốn**; giá vốn
  chỉ có ở `product.unit_cost`, và giá trị đó thay đổi theo thời gian. Muốn tính lợi nhuận gộp đúng
  thì phải lấy phiên bản `product` có hiệu lực tại thời điểm bán (quyết định ở bước 3 và 5).

**Trạng thái giao dịch (đã chốt):** fact chỉ chứa giao dịch `completed`, không có cột status và không
phân tích đổi trả. Việc một đơn đổi trạng thái sau khi đã nạp (ví dụ `completed` sang `returned`)
nằm ngoài phạm vi: coi hóa đơn không đổi sau khi ghi.

## Bước 3. Dimensions

Mỗi dimension trả lời "ai, cái gì, ở đâu, khi nào, thế nào" của một dòng hàng. Với grain ở bước 2,
có 7 dimension và 2 degenerate dimension. Loại SCD của từng dimension để bước 5.

| Dimension | Trả lời | Nguồn | Thuộc tính đề xuất |
|---|---|---|---|
| `dim_date` | Khi nào (ngày) | sinh từ lịch, không có trong nguồn | ngày, năm, quý, tháng, tuần, thứ, cuối tuần |
| `dim_time` | Khi nào (giờ trong ngày) | sinh sẵn 1.440 dòng (mỗi phút) | giờ, phút, khung giờ (sáng/trưa/chiều/tối) |
| `dim_product` | Bán cái gì | `product` + `category` + `brand` | SKU, tên, danh mục, thương hiệu, giá bán, giá vốn |
| `dim_store` | Bán ở đâu | `store` (qua `sales_transaction.store_id`) | tên cửa hàng, địa chỉ, số điện thoại |
| `dim_employee` | Ai thu ngân | `employee` | họ tên, cửa hàng đang làm, ngày vào làm, ngày nghỉ việc |
| `dim_payment_method` | Thanh toán thế nào | `payment_method` | tên phương thức |
| `dim_promotion` | Khuyến mãi nào | `promotion` | loại (phần trăm hoặc số tiền cố định), giá trị, ngày bắt đầu, ngày kết thúc, nhãn hiển thị |

Degenerate dimension (nằm thẳng trong fact, không có bảng riêng): `transaction_id` và `line_number`.

Các điểm đã suy ra từ nguồn:

- **Category và brand gộp vào `dim_product`** (star schema, không snowflake). Nguồn tách chúng ra
  chỉ để đạt 3NF, còn ở mô hình phân tích thì không cần.
- **Cửa hàng của hóa đơn khác cửa hàng của nhân viên.** `sales_transaction.store_id` là nơi bán;
  `employee.store_id` là nơi nhân viên đang làm và có thể đổi. Fact giữ khóa `dim_store` theo hóa
  đơn; cửa hàng của nhân viên chỉ là thuộc tính của `dim_employee`.
- **`dim_product` chứa giá vốn và giá bán**, vì đó là thứ thay đổi theo thời gian và là lý do cần
  history (bước 2).
- **Không có dimension cho trạng thái giao dịch**, vì fact chỉ chứa `completed` và việc đổi trạng thái
  đơn sau khi nạp nằm ngoài phạm vi (xem bước 2).
- **`dim_promotion` không có tên** vì nguồn không có cột tên, nên sinh cột nhãn hiển thị từ loại và
  giá trị (ví dụ "Giảm 10%", "Giảm 20.000đ").

Các quyết định đã chốt:

1. **Thêm `dim_time`, giữ `transaction_ts` trong fact.** Seed sinh giờ bán từ 7h đến 21h, cao điểm
   quanh 18h, nên phân tích theo khung giờ có ý nghĩa. Tách ngày và giờ thành hai dimension nhỏ thay
   vì một dimension theo từng phút của cả năm. `transaction_ts` vẫn phải nằm trong fact vì phép nối
   vào phiên bản lịch sử của `dim_product` cần thời điểm chính xác, `date_key` + `time_key` không
   thay được.
2. **Giữ thông tin cá nhân trong `dim_employee`** (ngày sinh, địa chỉ, số điện thoại, lương) để dành
   cho phần thực hành bảo mật dữ liệu sau. Khi viết dbt, gắn nhãn `meta: {pii: true}` cho các cột
   này trong file YAML để sau áp masking policy theo nhãn.
3. **Dòng hàng không khuyến mãi dùng thành viên cố định `-1` "No promotion"**, nên khóa trong fact
   không bao giờ rỗng. Thêm thành viên `-2` "Unknown" cho khóa chưa có trong dimension (dữ liệu đến
   muộn); cùng quy ước `-2` cho các dimension khác.

Ghi chú chuyển sang bước 5: `salary` thay đổi thường xuyên, nếu đưa vào cột theo dõi lịch sử thì mỗi
lần tăng lương sinh một phiên bản nhân viên. Chỉ nên theo dõi `store_id`; `salary` cập nhật đè.

## Bước 4. Facts

Fact `fact_sales`, grain là một dòng hàng của hóa đơn `completed`. Tất cả số đo tiền và số lượng đều
cộng dồn được (additive) trừ hai đơn giá `regular_price` và `unit_cost`. Các tỷ lệ (biên lợi nhuận
gộp, giá trị trung bình mỗi hóa đơn) không lưu vào fact; định nghĩa thành metric trong Preset, ví dụ
`SUM(gross_profit) / SUM(net_amount)`, để không ai vô tình lấy trung bình của các tỷ lệ.

**Khóa và thuộc tính trong fact:** `date_key`, `time_key`, `product_key`, `store_key`, `employee_key`,
`payment_method_key`, `promotion_key`, `transaction_id`, `line_number`, `transaction_ts`.

**Số đo:**

| Số đo | Cách có được | Cộng dồn |
|---|---|---|
| `quantity` | nguồn | có |
| `regular_price` | nguồn (giá tại lúc bán) | không, đơn giá |
| `unit_cost` | giá vốn của phiên bản product có hiệu lực tại `transaction_ts` | không, đơn giá |
| `gross_amount` | `quantity × regular_price` | có |
| `discount_amount` | giảm giá khuyến mãi, công thức bên dưới | có |
| `coupon_amount` | nguồn | có |
| `net_amount` | `gross_amount − discount_amount − coupon_amount` | có |
| `cost_amount` | `quantity × unit_cost` | có |
| `gross_profit` | `net_amount − cost_amount` | có |

### Quy ước khuyến mãi và coupon

Nguồn không lưu số tiền giảm của khuyến mãi (dòng hàng chỉ có `promotion_id`) và không nói tính theo
đơn vị hay theo dòng, nên quy ước sau được chốt ở đây:

- **Khuyến mãi tính theo đơn vị**, nhân với số lượng:
  - phần trăm: `discount_amount = quantity × regular_price × amount / 100`
  - số tiền cố định: `discount_amount = quantity × MIN(amount, regular_price)`
  Hàm `MIN` chặn trường hợp giá sau giảm bị âm. Quy ước này khớp với seed: khuyến mãi số tiền cố
  định chỉ gán cho sản phẩm có `unit_price >= amount × 4`, tức mức giảm luôn nhỏ hơn giá một đơn vị.
- **`coupon_amount` tính theo dòng**, không nhân với số lượng. Seed gán một lần cho cả dòng.
- Khi sửa `seed.py` hoặc `stream.py`, phải giữ đúng hai quy ước này.

### Giá vốn ghi vào fact lúc nạp

`unit_cost` và `cost_amount` được ghi vào fact lúc nạp. `unit_cost` phải lấy từ **phiên bản của
`dim_product` có hiệu lực tại `transaction_ts`** (range join, bước 5), không lấy từ product hiện tại
ở tầng silver: lấy từ bảng hiện tại thì đúng lúc nạp, nhưng khi chạy full refresh toàn bộ lịch sử bị
tính lại theo giá vốn mới, đúng lỗi mà SCD2 sinh ra để tránh.

Lý do ghi vào fact:

- Preset truy vấn đơn giản: lợi nhuận gộp chỉ cần `SUM` trên fact, không phải nối theo khoảng thời
  gian mỗi lần mở dashboard.
- Số đã báo cáo giữ nguyên; một hóa đơn chỉ được tính lại khi nạp lại.
- Vẫn truy vết được: `product_key` trỏ đúng phiên bản sản phẩm, nên có thể kiểm tra chéo `unit_cost`
  bằng cách nối.

Giới hạn cần biết: nếu nguồn sửa sai giá vốn của một ngày trong quá khứ thì fact không tự cập nhật,
trừ khi chạy full refresh. Với dự án portfolio thì chấp nhận được.

### Kiểm tra dữ liệu (dbt test)

`net_amount >= 0` và `discount_amount <= gross_amount`. Hai test này bắt ngay khi generator hoặc
stream vi phạm quy ước khuyến mãi.

## Bước 5. Loại dimension (SCD)

| Dimension | Loại | Lý do |
|---|---|---|
| `dim_date` | Type 0 | sinh từ lịch, không bao giờ đổi |
| `dim_time` | Type 0 | sinh sẵn 1.440 phút, không bao giờ đổi |
| `dim_product` | **Type 2** | giá vốn và giá bán đổi theo thời gian, cần để tính lợi nhuận gộp đúng lúc bán |
| `dim_employee` | **Type 2** | cửa hàng của nhân viên đổi, cần biết nhân viên làm ở đâu lúc bán |
| `dim_store` | Type 1 | `stream.py` không đổi cửa hàng; nếu nguồn sửa thì ghi đè |
| `dim_payment_method` | Type 1 | danh mục nhỏ, ghi đè |
| `dim_promotion` | Type 1 | chương trình có ngày bắt đầu và kết thúc cố định, ghi đè nếu nguồn sửa (hóa đơn cũ giữ nguyên, xem bên dưới) |

Mọi dimension có thành viên `-2` "Unknown"; riêng `dim_promotion` còn có `-1` "No promotion"
(bước 3).

### Cột nào tạo phiên bản mới (Type 2)

- **`dim_product`:** `unit_cost`, `unit_price`, `category_id`, `brand_id`. Tên sản phẩm cập nhật đè
  (Type 1), vì thường chỉ đổi khi sửa chính tả. Nguồn hiện không đổi danh mục và thương hiệu nên
  theo dõi hai cột này không sinh thêm phiên bản; nếu sau này một sản phẩm đổi ngành hàng thì doanh
  thu quá khứ theo danh mục vẫn đúng. Danh sách cột theo dõi đổi được với chi phí thấp: lịch sử nằm
  trong RAW nên chỉ cần sửa code rồi chạy full refresh của dbt.
- **`dim_employee`:** chỉ `store_id`. `salary` và các cột còn lại cập nhật đè (Type 1) bằng giá trị
  mới nhất, vì lương đổi thường xuyên và mỗi lần tăng lương sẽ sinh thêm một phiên bản không cần
  thiết. Các cột cá nhân gắn nhãn `meta: {pii: true}` (bước 3).

### Cách dựng phiên bản từ RAW

Ingest ghi mỗi lần một dòng `product` hoặc `employee` đổi thành một dòng mới trong RAW (cùng `id`,
`updated_at` mới; xem Project-Spec mục 9.2). SCD2 dựng thẳng từ các dòng đó bằng window function,
không dùng `dbt snapshot`: RAW đã giữ đủ các phiên bản, snapshot chỉ thêm một bản sao lịch sử thứ hai
và không dựng lại được, còn window function idempotent (`dbt build --full-refresh` bao nhiêu lần
cũng ra cùng kết quả). Về độ chi tiết thì hai cách như nhau.

0. **Staging khử trùng lặp trước.** Cursor incremental có thể nạp lại các dòng nằm ngay ở biên, nên
   staging giữ một dòng cho mỗi (`id`, `updated_at`):
   `qualify row_number() over (partition by id, updated_at order by _dlt_load_id desc) = 1`.
1. Sắp các dòng của một khóa nghiệp vụ theo `updated_at`.
2. **So từng dòng với dòng liền trước bằng `LAG` và `IS DISTINCT FROM`**, chỉ giữ dòng mà cột theo
   dõi đổi. Không dùng `DISTINCT` hay gom nhóm theo giá trị: chuỗi giá A → B → A phải ra 3 phiên
   bản, gom nhóm sẽ gộp hai lần A và làm sai khoảng hiệu lực. `IS DISTINCT FROM` cũng xử lý đúng
   `NULL`.
3. `valid_from` = `updated_at` của dòng đó; `valid_to` = `valid_from` của phiên bản kế tiếp.
   Phiên bản cuối có `valid_to = '9999-12-31'` và `is_current = true`.
4. **Phiên bản đầu tiên của mỗi khóa có `valid_from = '1900-01-01'`.** Dòng đầu tiên trong RAW chỉ
   xuất hiện khi ingest lần đầu, sau toàn bộ giao dịch lịch sử của seed; nếu dùng `updated_at` thật
   thì 100.000 đơn seed không khớp phiên bản nào.
5. **Cột Type 1 phải lấy giá trị mới nhất của khóa.** Sau bước 2, các cột như `salary` hay
   `product_name` vẫn mang giá trị tại thời điểm của dòng phiên bản, tức là thành "Type 2 không đầy
   đủ". Phải nối với dòng mới nhất của khóa và ghi đè các cột này lên mọi phiên bản.

Khuôn mẫu cho `dim_employee` (`dim_product` dùng cùng khuôn, chỉ đổi điều kiện so sánh thành
`unit_cost`, `unit_price`, `category_id`, `brand_id`):

```sql
with ordered as (
    select *,
           lag(store_id) over (partition by id order by updated_at) as prev_store_id
    from {{ ref('stg_employee') }}
),
versions as (
    select id, store_id, updated_at
    from ordered
    where prev_store_id is null or store_id is distinct from prev_store_id
),
latest as (
    select * from {{ ref('stg_employee') }}
    qualify row_number() over (partition by id order by updated_at desc) = 1
)
select
    {{ dbt_utils.generate_surrogate_key(['v.id', 'v.updated_at']) }} as employee_key,
    v.id as employee_id,
    v.store_id,                                           -- Type 2
    l.first_name, l.last_name, l.salary, l.end_date,      -- Type 1: giá trị mới nhất
    case when row_number() over (partition by v.id order by v.updated_at) = 1
         then '1900-01-01'::timestamp_tz else v.updated_at end as valid_from,
    coalesce(lead(v.updated_at) over (partition by v.id order by v.updated_at),
             '9999-12-31'::timestamp_tz) as valid_to,
    valid_to = '9999-12-31'::timestamp_tz as is_current
from versions v
join latest l on l.id = v.id
```

Khóa thay thế (surrogate key) của dimension: băm từ khóa nghiệp vụ và `updated_at` của phiên bản.
Quy ước biên: `valid_from <= transaction_ts < valid_to`.

Hệ quả:

- **RAW là nơi duy nhất giữ lịch sử.** Không chạy dlt với `refresh="drop_sources"`/`drop_resources`
  hay `replace` trên bảng `product` và `employee`, vì sẽ mất toàn bộ SCD2.
- **`dim_promotion` Type 1:** `discount_amount` được tính và ghi vào fact lúc nạp, giống `unit_cost`,
  nên sửa một khuyến mãi thì hóa đơn cũ giữ nguyên, chỉ đổi khi chạy full refresh (cùng giới hạn đã
  ghi ở bước 4).

### Nối fact vào phiên bản

`fact_sales` nối `dim_product` và `dim_employee` bằng khóa nghiệp vụ (`product_id`, `employee_id`)
và khoảng `valid_from <= transaction_ts < valid_to`. Fact giữ `product_key` và `employee_key` trỏ
đúng phiên bản.

Giới hạn (đã ghi ở Project-Spec mục 9.2): mỗi cycle `stream.py` phải được ingest trước cycle kế tiếp,
nếu không phiên bản trung gian bị mất.

## Bước 6. Loại bảng fact

| Loại | Dùng cho | Áp dụng ở đây |
|---|---|---|
| **Transaction fact** | mỗi dòng là một sự kiện xảy ra tại một thời điểm | **`fact_sales`** |
| Periodic snapshot | trạng thái định kỳ (ví dụ tồn kho cuối ngày) | không dùng, tồn kho ngoài phạm vi |
| Accumulating snapshot | quy trình có nhiều mốc thời gian, dòng được cập nhật khi qua mốc (đặt hàng → giao hàng → thanh toán) | không dùng, nguồn không có vòng đời nhiều mốc |
| Factless fact | ghi nhận quan hệ, không có số đo | để sau: promotion coverage |

**`fact_sales` là transaction fact.** Mỗi dòng hàng là một sự kiện bán tại `transaction_ts`, sinh ra
một lần và không đổi sau đó. Đặc điểm:

- grain nguyên tử (bước 2), số đo cộng dồn được (bước 4), dày: mọi dòng đều có đủ số đo;
- nạp incremental theo (`transaction_id`, `line_number`); đơn không đổi sau khi ghi nên không cần
  xử lý xóa hay cập nhật;
- mỗi dòng gắn với thời gian qua `date_key` và `time_key`, và giữ `transaction_ts` để nối phiên bản
  SCD2 (bước 5).

Các fact khác, cùng nguồn `fact_sales`, làm sau khi `fact_sales` chạy ổn:

- **`fact_sales_transaction`** (mart tổng hợp, grain một hóa đơn): basket size, giá trị trung bình
  mỗi hóa đơn. Dựng từ `fact_sales`, không đổi grain của `fact_sales`.
- **Promotion coverage** (factless fact): sản phẩm nào đang có khuyến mãi nhưng không bán được.
  Dựng từ `promotion_product` × `dim_date` trong khoảng `start_date`–`end_date`.

Hai fact bổ sung chỉ giữ trong doc này cho đến khi cần; chưa đưa vào Project-Spec mục 10.2.
