# Operational data model (OLTP)

Before thinking about the warehouse, you need to understand what the **source** data looks like. A point-of-sale (POS) system records each receipt
in a few milliseconds, so it is designed to **write fast and write correctly**, not for analysis. This page walks through the three design steps
for the PostgreSQL source: Conceptual → Logical (3NF) → Physical. The next part, the warehouse model, is in
[analytical-data-modeling.md](analytical-data-modeling.md). The actual DDL: `infras/postgres/init/01_schema.sql`.

## 1. Conceptual: what exists and how it connects

The first step says nothing about tables or columns yet. We only ask: which **entities** does this business have, and which **events** connect
them?

There are four entities here: **Store**, **Employee**, **Product** and **Promotion**,
connected by two events:

- **Buy**: a cashier sells products at a store, possibly applying an active promotion. Each sale
  must record the time, payment method, quantity, list price and coupon, because that is the raw material for analyzing prices and
  promotions.
- **Stocks**: a periodic snapshot of each store's stock levels. This event is in the model to leave room for the supply
  chain later, but it is **out of scope** for the project and is not used.

![Figure 1. Conceptual model](../../assets/diagrams/Conceptual_Model_Modeling.drawio.svg)

Further reading: [Entity–relationship model](https://en.wikipedia.org/wiki/Entity%E2%80%93relationship_model).

## 2. Logical: turn it into tables, then normalize to 3NF

Going from the conceptual diagram to the logical one is a mechanical translation:
- Entities become **tables**, attributes become **columns**.
- 1:N relationships become **foreign keys**.
- M:N relationships become a **junction table**.

![Figure 2. Logical model (not normalized)](../../assets/diagrams/Logical_Model_Diagram.drawio.svg)

Then normalize to **third normal form (3NF)**. Put simply: each piece of information is stored in **one place** only. Renaming a brand
means editing exactly one row, not thousands of product rows. *Without normalization:* data repeats, you fix one copy and forget another,
and two rows about the same thing can contradict each other.

![Figure 3. Logical model after 3NF normalization](../../assets/diagrams/Logical_Model_Diagram_Normalize_3NF.drawio.svg)

The result is **ten tables**, in three groups:

| Group | Tables | Notes |
|---|---|---|
| Entities and lookups | `store`, `employee`, `product`, `promotion` + `category`, `brand`, `payment_method` | Category, brand and payment method are split into their own tables to remove transitive dependencies (reaching 3NF) |
| Transactions (header and detail split) | `sales_transaction`, `sales_transaction_item` | The header holds receipt-wide information (store, cashier, payment, time); the detail holds each line item. They are split so a multi-line receipt does not repeat the header information |
| Junction table | `promotion_product` | Resolves the M:N relationship between products and promotions |

Further reading: [Third normal form](https://en.wikipedia.org/wiki/Third_normal_form).

## 3. Physical: choose PostgreSQL and write constraints

Logical only says *what* is stored. Physical answers *what it is stored in and how it is kept correct*. The project chooses **PostgreSQL** because
it supports strict transactions, strict data types and exact decimal numbers for money.

![Figure 4. Physical model](../../assets/diagrams/Physical_Model_Diagram.drawio.svg)

The most notable thing at this layer is the **constraints** that block bad data at the door, before it flows down to the warehouse.
Below are the two sales tables and the promotion table, taken from the actual DDL:

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
    promotion_id    BIGINT,                                   -- NULL = no promotion
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    regular_price   NUMERIC(12, 2) NOT NULL CHECK (regular_price >= 0),   -- price at the time of sale
    coupon_amount   NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (coupon_amount >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, line_number),
    CONSTRAINT fk_item_promotion_product
        FOREIGN KEY (product_id, promotion_id)
        REFERENCES promotion_product (product_id, promotion_id)
);
```

| Constraint | What it guarantees | If missing |
|---|---|---|
| Composite primary key `(transaction_id, line_number)` | No two lines with the same number on one receipt | Duplicate detail lines, revenue counted twice |
| `ON DELETE CASCADE` on `transaction_id` | Deleting a receipt removes its detail lines, leaving no orphan rows | The foreign key rejects deleting the receipt; each detail line has to be deleted by hand first |
| Composite foreign key `(product_id, promotion_id)` to `promotion_product` | Blocks applying a promotion to a product that is not in that campaign. When `promotion_id` is empty, the check is skipped | Discounts on the wrong products slip into the data |
| `CHECK (amount <= 100)` for `percentage` | Blocks discounts over 100% | Negative revenue |
| `NUMERIC(12, 2)` for money | Blocks floating-point rounding errors | Sums drift by small amounts |
| `CHECK` for status and promotion type (`VARCHAR` instead of `ENUM`) | Blocks unexpected values like `refunded` | Unexpected values spread deep into the data. `CHECK` is used instead of `ENUM` so changing the set of values only means editing one constraint, not `ALTER TYPE` |

### Audit columns and incremental loading

Every table has `created_at` and `updated_at` (`TIMESTAMPTZ`, with time zone), and a **trigger** updates `updated_at` automatically whenever
a row is UPDATEd. It sounds boring, but it is the foundation of the whole pipeline downstream: dlt uses `updated_at` as a cursor to load only new
data ([phase 3](../phases/03-ingestion-snowflake.md)), and dbt builds SCD2 history from versions with different `updated_at` values
([phase 5](../phases/05-dbt.md)). The four incrementally loaded tables (`sales_transaction`, `sales_transaction_item`, `product`, `employee`) have an index on `updated_at` so the query "which rows are newer than point X" is fast.

*If skipped:* an UPDATE that does not change `updated_at` is invisible to dlt, and RAW drifts from the source without any error.

The project uses this query-based incremental loading. An alternative is log-based CDC (such as Debezium), which captures every intermediate
change, but CDC is out of the current scope; `wal_level=logical` is already enabled in `docker-compose.yml` for later.

Further reading: [PostgreSQL: constraints](https://www.postgresql.org/docs/16/ddl-constraints.html),
[PL/pgSQL triggers](https://www.postgresql.org/docs/16/plpgsql-trigger.html).
