# Retail Pulse

**Từ một tờ hóa đơn đến dashboard lợi nhuận: xây pipeline dữ liệu bán lẻ end-to-end.**

PostgreSQL → dlt → Snowflake → dbt → Dagster → Preset, kiểm tra bằng Great Expectations và GitHub Actions. Chạy được trên một chiếc laptop.

![Hóa đơn tính tiền mẫu](./assets/diagrams/Sample_cash_register_receipt.png)

Mỗi lần bạn thanh toán ở siêu thị, một tờ hóa đơn như trên ra đời. Với người mua, nó là mảnh giấy để vứt đi. Với chuỗi bán lẻ, nó là mỏ vàng: mỗi dòng cho biết **bán gì, bao nhiêu, ở đâu, lúc nào, giá nào, có khuyến mãi không**.

Vấn đề là mỏ vàng đó nằm rải rác trong cơ sở dữ liệu của hệ thống bán hàng (POS), thiết kế để ghi nhanh chứ không để phân tích. Dự án này đi hết quãng đường từ đó đến một dashboard trả lời được những câu hỏi như:

- Cửa hàng nào và sản phẩm nào lãi nhiều nhất?
- Khuyến mãi nào thật sự hiệu quả, khuyến mãi nào chỉ cho đi?
- Giá vốn tăng 3% thì lợi nhuận thay đổi ra sao?

Khách hàng, tồn kho, trả hàng và hủy đơn nằm ngoài phạm vi, để tập trung làm đúng một quy trình: **bán hàng**.

> **Phạm vi nạp dữ liệu:** incremental theo cột `updated_at` (batch). CDC dựa trên log (Debezium, Redpanda) chưa làm; xem [Project-Spec](./docs/Project-Spec.md).
> **Tài liệu:** lộ trình theo phase, hướng dẫn chạy và thiết kế nằm ở [docs/README.md](./docs/README.md).

# 1. Bắt đầu từ nguồn: mô hình dữ liệu vận hành

Trước khi nghĩ đến warehouse, phải hiểu dữ liệu nguồn trông thế nào. Hệ thống POS giả lập được mô hình hóa qua ba bước: Conceptual (có những thực thể nào) → Logical (3NF, 10 bảng) → Physical (PostgreSQL).

Trọng tâm là hai bảng: `sales_transaction` là **header** (một lần thanh toán), `sales_transaction_item` là **từng dòng hàng** trên hóa đơn. Mọi phân tích về doanh thu đều xuất phát từ dòng hàng này.

Sơ đồ và lý do thiết kế: [Mô hình dữ liệu vận hành](./docs/design/operational-data-modeling.md). Phía warehouse: [Mô hình phân tích](./docs/design/analytical-data-modeling.md).

# 2. Kiến trúc: nhìn như một nhà hàng

Cách dễ nhất để hình dung pipeline là một nhà hàng. **Nguyên liệu** (dữ liệu thô) về kho, được **sơ chế** (làm sạch, chuẩn hóa), **nấu** (áp dụng logic nghiệp vụ), rồi **bày đĩa** (star schema) cho khách ăn (dashboard). Còn một quản lý đứng ngoài lo lịch, và một người kiểm tra chất lượng ở mọi công đoạn.

## A. Bức tranh lớn

Một đường chính từ trái sang phải. Hai khối phía dưới không chứa dữ liệu mà điều khiển các khối còn lại.

```mermaid
flowchart LR
  SRC[("Nguồn<br/>CSDL OLTP")]
  ING["Nạp dữ liệu<br/>(ingestion)"]

  SRC <-->|"Extract"| ING
  ING -->|"Load"| RAW

  subgraph DWH["Snowflake"]
    direction LR
    subgraph L1["Dữ liệu thô của CSDL nguồn"]
      RAW["Raw"]
    end
    subgraph L2["Chuẩn hóa"]
      STG["Staging"]
    end
    subgraph L3["Star schema"]
      MART["Data warehouse"]
    end
    RAW --> STG --> MART
  end

  BI["BI<br/>Dashboard"]
  MART --> BI

  TRF["Biến đổi & chất lượng dữ liệu"]
  TRF -.- RAW
  TRF -.- STG
  TRF -.- MART

  ORC["Điều phối & CI/CD"]
  ORC -.-> ING
  ORC -.-> TRF

  classDef src fill:#C62828,stroke:#8E0000,color:#FFFFFF
  classDef layer fill:#BBDEFB,stroke:#1565C0,color:#0D47A1
  classDef tool fill:#F57C00,stroke:#E65100,color:#FFFFFF
  classDef bi fill:#2E7D32,stroke:#1B5E20,color:#FFFFFF
  classDef ops fill:#ECEFF1,stroke:#455A64,color:#263238

  class SRC,ING src
  class RAW,STG,MART layer
  class TRF tool
  class BI bi
  class ORC ops
```

## B. Gắn với công cụ thật

Cùng luồng trên, nhưng mỗi ô là một công cụ cụ thể. Bronze, Silver, Gold là cách gọi của kiến trúc Medallion: càng sang phải dữ liệu càng sạch và càng gần câu hỏi nghiệp vụ.

```mermaid
flowchart LR
  subgraph LOCAL["Máy local - Docker Compose"]
    direction TB
    GEN["Bộ sinh dữ liệu<br/>Python + SQLAlchemy + Faker<br/>seed / stream"]
    PG[("PostgreSQL<br/>OLTP - 3NF")]
    GEN -->|insert / update| PG
  end

  DLT["dlt<br/>ingestion pipeline"]

  PG -->|"Extract PostgreSQL<br/>Load lần đầu → Incremental"| DLT
  DLT -->|"Load vào<br/>Snowflake RAW"| RAW

  subgraph SF["Snowflake"]
    direction LR
    subgraph L1["Dữ liệu thô từ PostgreSQL"]
      RAW["Raw<br/>(Bronze)"]
    end
    subgraph L2["Chuẩn hóa"]
      STG["Staging<br/>(Silver)"]
    end
    subgraph L3["Logic nghiệp vụ"]
      INT["Intermediate<br/>(Silver)"]
    end
    subgraph L4["Star schema - Kimball"]
      MART["Data marts<br/>(Gold)"]
    end
    RAW --> STG --> INT --> MART
  end

  BI["Preset<br/>Dashboard Revenue,<br/>Product, Store"]
  MART --> BI

  DBT["dbt-core - chạy local<br/>transform + dbt test"]
  GE["Great Expectations<br/>kiểm tra RAW"]

  DBT -.- STG
  DBT -.- INT
  DBT -.- MART
  GE -.- RAW

  DAG["Dagster<br/>dagster-dlt + dagster-dbt<br/>asset, job, lịch chạy"]
  CI["GitHub Actions<br/>ruff + dbt slim CI"]

  DAG ==>|điều phối| DLT
  DAG ==> GE
  DAG ==> DBT
  CI -.->|kiểm tra PR| DBT

  classDef src fill:#C62828,stroke:#8E0000,color:#FFFFFF
  classDef layer fill:#BBDEFB,stroke:#1565C0,color:#0D47A1
  classDef tool fill:#F57C00,stroke:#E65100,color:#FFFFFF
  classDef bi fill:#2E7D32,stroke:#1B5E20,color:#FFFFFF
  classDef ops fill:#ECEFF1,stroke:#455A64,color:#263238

  class GEN,PG,DLT src
  class RAW,STG,INT,MART layer
  class DBT,GE tool
  class BI bi
  class DAG,CI ops
```

# 3. Những quyết định đáng kể

Vài lựa chọn quyết định hình dạng của dự án, và lý do:

- **RAW chỉ ghi thêm, không bao giờ ghi đè.** Khi giá một sản phẩm đổi, dlt thêm một dòng mới thay vì sửa dòng cũ. Nhờ vậy lịch sử không mất, và đó là nguyên liệu để dựng SCD2. Cái giá: xóa RAW là mất lịch sử vĩnh viễn, nên mọi lệnh có thể xóa RAW đều được cảnh báo trong tài liệu.
- **SCD2 tự xây bằng window function, không dùng `dbt snapshot`.** Với dữ liệu append-only, so sánh dòng hiện tại với dòng liền trước (`LAG`) cho ra các khoảng thời gian hiệu lực mà vẫn kiểm soát được từng bước. Một giao dịch luôn được gắn với giá vốn **của đúng thời điểm bán**.
- **Chỉ giao dịch `completed` đi vào phân tích.** Bộ lọc nằm ở staging, từ tầng sau không ai phải nhớ đến cột `status`.
- **Dữ liệu đến trễ không viết logic vá riêng.** Dòng fact không khớp được dimension sẽ mang khóa `-2` ("Unknown"), và được sửa bằng cách dựng lại bảng fact (`--full-refresh`) chứ không phức tạp hóa bước incremental.
- **Mọi thay đổi đi qua pull request.** CI chạy dbt trên một database riêng, chỉ build phần bị đổi (slim CI), nên không đụng dữ liệu thật.

# 4. Dự án gồm những gì

Hình dưới là cùng pipeline nhìn theo công cụ: dữ liệu đi từ trái sang phải ở hàng giữa, dbt dựng các tầng Snowflake ở hàng dưới, Dagster và GitHub CI nằm phía trên làm lớp điều khiển.

![Kiến trúc công cụ RetailPulse](./assets/diagrams/retailpulse-tool.png)

> Ảnh vẽ từ bản thiết kế ban đầu nên khác thực tế ở ba điểm: CI hiện chỉ có `ruff` và slim CI (chưa có `sqlfluff`, chưa tự deploy); dbt không dùng snapshot (SCD2 tự xây bằng window function); Great Expectations chưa có trong ảnh.

| Công cụ | Vai trò | Trạng thái |
| --- | --- | --- |
| Python generator (SQLAlchemy, Faker) | Seed dữ liệu lịch sử, mô phỏng đổi giá, đổi cửa hàng nhân viên và bán hàng mới | Xong |
| PostgreSQL 16 (Docker Compose) | CSDL nguồn OLTP, 3NF | Xong |
| dlt | Nạp incremental từ PostgreSQL vào Snowflake RAW | Xong |
| Snowflake | Các tầng RAW, staging, intermediate, marts | Xong |
| dbt Core | Staging, intermediate, marts, dimension SCD2, test | Xong |
| Dagster | Điều phối dlt, dbt và kiểm tra chất lượng thành asset, job, lịch chạy hằng ngày | Xong |
| Preset | Dashboard BI trên marts | Xong |
| Great Expectations | Kiểm tra chất lượng dữ liệu RAW | Xong |
| GitHub Actions | Lint `ruff`, slim CI cho dbt, bảo vệ nhánh `main` | Xong (chưa có CD, `sqlfluff`, `pytest`) |

Muốn chạy thử? Bắt đầu từ [docs/README.md](./docs/README.md): có lộ trình theo phase và các lệnh chạy nhanh.
