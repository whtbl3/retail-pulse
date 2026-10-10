# Mô hình dữ liệu vận hành (OLTP)

Trước khi nghĩ đến warehouse, phải hiểu dữ liệu **nguồn** trông thế nào. Một hệ thống bán hàng (POS) ghi mỗi hóa đơn
trong vài mili giây, nên nó được thiết kế để **ghi nhanh và không sai**, chứ không để phân tích. Bài này đi qua ba bước thiết
kế nguồn PostgreSQL: Conceptual → Logical (3NF) → Physical. Phần tiếp theo, mô hình cho warehouse, nằm ở
[analytical-data-modeling.md](analytical-data-modeling.md). DDL thật: `infras/postgres/init/01_schema.sql`.

## 1. Conceptual: có những thứ gì, nối với nhau ra sao

Bước đầu chưa nói gì đến bảng hay cột. Ta chỉ hỏi: nghiệp vụ này có những **thực thể** nào, và những **sự kiện** nào nối
chúng lại?

Ở đây có bốn thực thể: **Store** (cửa hàng), **Employee** (nhân viên), **Product** (sản phẩm) và **Promotion** (khuyến mãi),
nối với nhau qua hai sự kiện:

- **Buy** (mua hàng): một nhân viên thu ngân bán sản phẩm tại một cửa hàng, có thể áp một khuyến mãi đang hiệu lực. Mỗi lần bán
  phải ghi đủ thời điểm, phương thức thanh toán, số lượng, giá niêm yết và coupon, vì đó là nguyên liệu để phân tích giá và
  khuyến mãi.
- **Stocks** (tồn kho): ảnh chụp định kỳ số lượng tồn của từng cửa hàng. Sự kiện này có trong mô hình để chừa chỗ cho chuỗi
  cung ứng về sau, nhưng **nằm ngoài phạm vi** của dự án và không được dùng.

![Hình 1. Mô hình Conceptual](../../assets/diagrams/Conceptual_Model_Modeling.drawio.svg)

Đọc thêm: [Entity–relationship model](https://en.wikipedia.org/wiki/Entity%E2%80%93relationship_model).

## 2. Logical: biến thành bảng, rồi chuẩn hóa đến 3NF

Từ sơ đồ conceptual sang logical là một phép dịch cơ học:
- Thực thể thành **bảng**, thuộc tính thành **cột**.
- Quan hệ 1:N thành **khóa ngoại**.
- Quan hệ M:N thành một **bảng trung gian**.

![Hình 2. Mô hình Logical (chưa chuẩn hóa)](../../assets/diagrams/Logical_Model_Diagram.drawio.svg)

Rồi áp dụng chuẩn hóa đến **dạng chuẩn 3 (3NF)**. Nói đơn giản: mỗi thông tin chỉ được lưu **một chỗ**. Đổi tên một nhãn hàng
thì sửa đúng một dòng, không phải sửa hàng nghìn dòng sản phẩm. *Nếu không chuẩn hóa:* dữ liệu lặp lại, sửa chỗ này quên chỗ
kia, và hai dòng cùng nói về một thứ có thể mâu thuẫn nhau.

![Hình 3. Mô hình Logical sau khi chuẩn hóa 3NF](../../assets/diagrams/Logical_Model_Diagram_Normalize_3NF.drawio.svg)

Kết quả là **mười bảng**, chia thành ba nhóm:

| Nhóm | Bảng | Ghi chú |
|---|---|---|
| Thực thể và danh mục | `store`, `employee`, `product`, `promotion` + `category`, `brand`, `payment_method` | Danh mục, nhãn hàng, phương thức thanh toán được tách thành bảng riêng để loại phụ thuộc bắc cầu (đạt 3NF) |
| Giao dịch (tách header và chi tiết) | `sales_transaction`, `sales_transaction_item` | Header giữ thông tin cả hóa đơn (cửa hàng, thu ngân, thanh toán, thời điểm); chi tiết giữ từng dòng hàng. Tách ra để một hóa đơn nhiều dòng không phải lặp lại thông tin header |
| Bảng trung gian | `promotion_product` | Giải quyết quan hệ M:N giữa sản phẩm và khuyến mãi |

Đọc thêm: [Third normal form](https://en.wikipedia.org/wiki/Third_normal_form).

## 3. Physical: chọn PostgreSQL và viết thành ràng buộc

Logical chỉ nói *cái gì* được lưu. Physical trả lời *lưu bằng gì và giữ cho đúng bằng cách nào*. Dự án chọn **PostgreSQL** vì
nó hỗ trợ giao dịch chặt chẽ, kiểu dữ liệu nghiêm ngặt và số thập phân chính xác cho tiền.

![Hình 4. Mô hình Physical](../../assets/diagrams/Physical_Model_Diagram.drawio.svg)

Điều đáng nói nhất ở tầng này là những **ràng buộc** để dữ liệu sai bị chặn ngay từ cửa vào, trước khi nó trôi xuống warehouse.
Dưới đây là hai bảng bán hàng và bảng khuyến mãi trích từ DDL thật:

```sql
CREATE TABLE promotion (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type        VARCHAR(20) NOT NULL CHECK (type IN ('percentage', 'fixed_amount')),
    amount      NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_promotion_dates   CHECK (end_date >= start_date),
    CONSTRAINT chk_promotion_percent CHECK (type <> 'percentage' OR amount <= 100)
);

CREATE TABLE sales_transaction_item (
    transaction_id  BIGINT NOT NULL REFERENCES sales_transaction (transaction_id) ON DELETE CASCADE,
    line_number     SMALLINT NOT NULL CHECK (line_number > 0),
    product_id      BIGINT NOT NULL REFERENCES product (id),
    promotion_id    BIGINT,                                   -- NULL = không khuyến mãi
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    regular_price   NUMERIC(12, 2) NOT NULL CHECK (regular_price >= 0),   -- giá tại thời điểm bán
    coupon_amount   NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (coupon_amount >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, line_number),
    CONSTRAINT fk_item_promotion_product
        FOREIGN KEY (product_id, promotion_id)
        REFERENCES promotion_product (product_id, promotion_id)
);
```

| Ràng buộc | Bảo đảm điều gì | Nếu thiếu |
|---|---|---|
| Khóa chính ghép `(transaction_id, line_number)` | Không có hai dòng cùng số thứ tự trong một hóa đơn | Dòng chi tiết trùng, doanh thu đếm đôi |
| `ON DELETE CASCADE` ở `transaction_id` | Xóa hóa đơn thì các dòng chi tiết đi theo, không để dòng mồ côi | Xóa hóa đơn bị khóa ngoại từ chối, phải xóa tay từng dòng chi tiết trước |
| Khóa ngoại ghép `(product_id, promotion_id)` tới `promotion_product` | Áp khuyến mãi cho sản phẩm không thuộc chương trình đó. Khi `promotion_id` rỗng thì bỏ qua kiểm tra | Giảm giá sai sản phẩm lọt vào dữ liệu |
| `CHECK (amount <= 100)` khi là `percentage` | Giảm giá trên 100% | Doanh thu âm |
| `NUMERIC(12, 2)` cho tiền | Sai số làm tròn của số thực | Cộng dồn lệch từng đồng |
| `CHECK` cho trạng thái và loại khuyến mãi (`VARCHAR` thay vì `ENUM`) | Giá trị lạ như `refunded` | Giá trị lạ đi sâu vào dữ liệu. Dùng `CHECK` thay `ENUM` để đổi tập giá trị chỉ cần sửa một ràng buộc, không phải `ALTER TYPE` |

### Cột kiểm toán và nạp dữ liệu incremental

Mọi bảng đều có `created_at` và `updated_at` (`TIMESTAMPTZ`, có múi giờ), và một **trigger** tự cập nhật `updated_at` mỗi khi
dòng bị UPDATE. Nghe nhàm chán nhưng đây là nền móng của cả pipeline phía sau: dlt dùng `updated_at` làm con trỏ để chỉ nạp phần
mới ([phase 3](../phases/03-ingestion-snowflake.md)), và dbt dựng lịch sử SCD2 từ các phiên bản có `updated_at` khác nhau
([phase 5](../phases/05-dbt.md)). Bốn bảng nạp incremental (`sales_transaction`, `sales_transaction_item`, `product`, `employee`) có index trên `updated_at` để truy vấn "dòng nào mới hơn mốc X" nhanh.

*Nếu bỏ qua:* một UPDATE không đổi `updated_at` thì dlt không thấy thay đổi, RAW lệch nguồn mà không báo lỗi.

Dự án dùng cách nạp theo truy vấn này (query-based incremental). Một lựa chọn khác là CDC dựa trên log (như Debezium) bắt từng thay
đổi trung gian, nhưng CDC nằm ngoài phạm vi hiện tại; `wal_level=logical` được bật sẵn trong `docker-compose.yml` để dành cho sau.

Đọc thêm: [PostgreSQL: ràng buộc](https://www.postgresql.org/docs/16/ddl-constraints.html),
[trigger bằng PL/pgSQL](https://www.postgresql.org/docs/16/plpgsql-trigger.html).
