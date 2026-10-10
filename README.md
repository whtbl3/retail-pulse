# Retail Pulse

Building an End-to-End Analytics Engineering with Batch & CDC Streaming Data Platform: PostgreSQL, Debezium, Redpanda, dlt, Snowflake (Medallion & Kimball SCD2), dbt, Dagster, and Github CI/CD.

# Problem Definition: A Retail POS & Profit Optimization Analytics Case
In this challenge, our goal is to maximize enterprise profitability by optimizing logistics management alongside pricing and promotion strategies. To achieve this, we focus on Point of Sale (POS) sales operations as our core business process, as it serves as the primary source of detailed, accurate, and continuous transaction data. We require granular POS transaction records, including itemized purchases, sold quantities, store locations, timestamps, base prices, applied promotion codes, and final transaction amounts. Furthermore, integrating POS data with product cost margins and inventory levels is essential to track product movement and supply chain efficiency. By analyzing this dataset, we can uncover actionable insights to streamline inventory allocation, evaluate promotional effectiveness, refine pricing strategies, and drive sustainable profit growth.

![Sample cash register receipt](./assets/diagrams/Sample_cash_register_receipt.png)

> **Documentation:** phase-by-phase roadmap, run guides and component design notes live in
> [docs/README.md](./docs/README.md). The canonical specification is
> [docs/Project-Spec.md](./docs/Project-Spec.md).

# 1. Operational Data Modeling
Nguồn OLTP được mô hình hóa theo ba bước Conceptual → Logical (3NF, 10 bảng) → Physical (PostgreSQL),
gồm sales_transaction (header) và sales_transaction_item (line item) cho nghiệp vụ POS. Nội dung đầy
đủ và các sơ đồ: [docs/design/operational-data-modeling.md](./docs/design/operational-data-modeling.md).
Mô hình phân tích cho warehouse: [docs/design/analytical-data-modeling.md](./docs/design/analytical-data-modeling.md).

# 2 Data Architecture
## A. High-Level
```mermaid
flowchart LR
  SRC[("Source<br/>OLTP database")]
  ING["Ingestion<br/>pipeline"]

  SRC <-->|"Extract"| ING
  ING -->|"Load"| RAW

  subgraph DWH["Snowflake"]
    direction LR
    subgraph L1["Raw data of source DB"]
      RAW["Raw"]
    end
    subgraph L2["Standardized"]
      STG["Staging"]
    end
    subgraph L3["Star schema"]
      MART["Data warehouse"]
    end
    RAW --> STG --> MART
  end

  BI["BI<br/>Dashboards"]
  MART --> BI

  TRF["Transformation & Data quality"]
  TRF -.- RAW
  TRF -.- STG
  TRF -.- MART

  ORC["Orchestration & CI/CD"]
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
## B. Low-Level Data Architecture
```mermaid
flowchart LR
  subgraph LOCAL["Local - Docker Compose"]
    direction TB
    GEN["Data generator<br/>Python + SQLAlchemy + Faker<br/>batch / stream"]
    PG[("PostgreSQL<br/>OLTP - 3NF")]
    GEN -->|insert / update| PG
  end

  DLT["dlt<br/>ingestion pipeline"]

  PG -->|"Extract PostgreSQL<br/>Initial load → Incremental → CDC"| DLT
  DLT -->|"Load into<br/>Snowflake RAW"| RAW

  subgraph SF["Snowflake"]
    direction LR
    subgraph L1["Raw data of PostgreSQL"]
      RAW["Raw<br/>(Bronze)"]
    end
    subgraph L2["Standardized"]
      STG["Staging<br/>(Silver)"]
    end
    subgraph L3["Business logic"]
      INT["Intermediate<br/>(Silver)"]
    end
    subgraph L4["Star schema - Kimball"]
      MART["Data marts<br/>(Gold)"]
    end
    RAW --> STG --> INT --> MART
  end

  BI["Preset<br/>Revenue, Product,<br/>Store dashboards"]
  MART --> BI

  DBT["dbt-core - local<br/>transform + dbt tests"]
  GE["Great Expectations<br/>raw / bronze checks"]

  DBT -.- STG
  DBT -.- INT
  DBT -.- MART
  GE -.- RAW

  DAG["Dagster<br/>dagster-dlt + dagster-dbt<br/>assets, schedules, sensors"]
  CI["GitHub CI<br/>sqlfluff + ruff<br/>dbt build slim CI, deploy"]

  DAG ==>|orchestrates| DLT
  DAG ==> GE
  DAG ==> DBT
  CI -->|deploy| DAG

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

## C. Tool Architecture

The same pipeline seen as the tools that implement it. Data moves left to right through the middle row (generator → PostgreSQL → dlt → Snowflake RAW → dbt), dbt builds the Snowflake layers on the bottom row, and Dagster and GitHub CI sit above as the control plane.

![RetailPulse tool architecture](./assets/diagrams/retailpulse-tool.png)

| Tool | Role | Status |
| --- | --- | --- |
| Python generator (SQLAlchemy, Faker) | Seeds historical data and simulates product price/cost changes | Done |
| PostgreSQL 16 (Docker Compose) | Source OLTP database, 3NF | Done |
| dlt | Incremental ingestion from PostgreSQL to Snowflake RAW | Done |
| Snowflake | RAW, staging, intermediate and marts layers | RAW done |
| dbt Core | Staging, intermediate, marts, SCD2 dimensions, tests | Planned |
| Dagster | Orchestrates dlt and dbt as assets | Planned |
| Preset | BI dashboards on the marts | Planned |
| GitHub CI | Lint, test, deploy | Planned |
| Great Expectations | Optional data quality checks on RAW | Done |

See [docs/README.md](./docs/README.md) for the phase-by-phase roadmap.

