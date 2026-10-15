# Analytical data model (Kimball)

A supermarket receipt has three line items. When building a warehouse, the first question is not "which tool?" but: **what does one row
in the fact table represent?** One receipt? One line item? One day of sales? Get this wrong and everything after it is off.
This page follows Kimball's four-step design process (extended to six), based on the source described in
[operational-data-modeling.md](operational-data-modeling.md). The actual implementation is in [phase 5](../phases/05-dbt.md).

| Step | Content |
|---|---|
| 1 | Identify the business process |
| 2 | Declare the grain (what one fact row is) |
| 3 | Identify the dimensions |
| 4 | Identify the facts (measures) |
| 5 | Choose dimension types (Type 0, 1, 2) |
| 6 | Choose the fact table type |

Further reading: [Four-Step Dimensional Design Process](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/four-4-step-design-process/).

## Step 1. Business process

**Sales at the checkout counter (POS).** This is the `Buy` event in the conceptual model, and the only source that carries price, quantity,
promotion, store, cashier, payment method and time all at once.

Questions this process must answer (from the problem in the README):
- revenue and trends over time;
- performance by product, category and brand;
- performance by store (and cashier);
- promotion effectiveness;
- gross profit over time, using **the cost of goods at the time of sale**.

Promotions are **not** a separate process: in the source, a promotion is context for a line item (a dimension attached to the fact),
not an event with its own time and measures. A "promotion coverage" model (a factless fact from `promotion_product` × date) can be
added once the main fact works.

Out of scope: inventory (`Stocks`), returns and cancellations (only `completed` transactions are analyzed, see section 7.3 of Project-Spec).

Further reading: [Business Processes](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/business-process/).

## Step 2. Grain

**One fact row is one line item on a receipt, that is one `sales_transaction_item` (`transaction_id`, `line_number`), for
`completed` transactions only.**

*Why this level:* it is the finest level of detail in the source, so every question in step 1 can be rolled up from it without losing
information. A coarser grain (one row per receipt) could no longer answer "which product sells best". Consequences:

- `transaction_id` sits directly in the fact as a **degenerate dimension**. Receipt-level numbers (basket value, average transaction
  value) come from an aggregate table built on this fact, without changing the grain.
- Receipt attributes (store, cashier, payment, time) repeat on every line of the same receipt, so **counting receipts
  must use `COUNT(DISTINCT transaction_id)`**. *`COUNT(*)` counts line items, not receipts.*
- The source stores `regular_price` at the time of sale on the line item, but **does not store cost of goods**. Cost is only in `product.unit_cost`, and
  it changes over time. Correct profit requires the `product` version valid at the time of sale (decided in steps 3 and 5).

**Transaction status (settled):** the fact holds only `completed`, has no status column, and returns are not analyzed. A receipt that changes
status after it is loaded (for example `completed` to `returned`) is out of scope: a receipt is treated as unchanged once written.

Further reading: [Grain](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/),
[Degenerate Dimensions](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/degenerate-dimension/).

## Step 3. Dimensions

Each dimension answers one of "who, what, where, when, how" for a line item. With the grain from step 2 there are **7 dimensions and 2
degenerate dimensions**.

| Dimension | Answers | Source | Main attributes |
|---|---|---|---|
| `dim_date` | Which day | generated from a calendar, not in the source | date, year, quarter, month, week, weekday, weekend flag |
| `dim_time` | What time | pre-generated, 1,440 rows (one per minute) | hour, minute, AM/PM, day part (`Morning`, `Afternoon`, `Evening`, `Night`) |
| `dim_product` | What was sold | `product` + `category` + `brand` | SKU, name, category, brand, price, cost |
| `dim_store` | Where | `store` (via `sales_transaction.store_id`) | store name, address, phone number |
| `dim_employee` | Which cashier | `employee` | name, current store, hire date, termination date |
| `dim_payment_method` | How it was paid | `payment_method` | method name |
| `dim_promotion` | Which promotion | `promotion` | type (percentage or fixed amount), value, start date, end date, display label |

Degenerate dimensions (directly in the fact, no table of their own): `transaction_id` and `line_number`.

Takeaways from the source:

- **Category and brand are folded into `dim_product`** (star schema, not snowflake). The source splits them only to reach 3NF; the analytical
  model does not need that.
- **The receipt's store differs from the employee's store.** `sales_transaction.store_id` is where the transaction happened; `employee.store_id` is where the employee
  currently works, and it can change. The fact keeps the `dim_store` key of the receipt; the employee's store is only an attribute of `dim_employee`.
- **`dim_product` keeps price and cost** because they change over time, which is exactly why history is needed (step 2).
- **There is no dimension for transaction status**, because the fact holds only `completed`.
- **`dim_promotion` has no name** because the source has no name column, so the display label is generated from type and value: `15% off`, `10,000 VND off`
  (labels are in English across the dashboard).

**Settled decisions:**

1. **Add `dim_time` and keep `transaction_ts` in the fact.** Sales hours run from 07:00 to 21:00 with a peak around 18:00, so analysis by day part
   is meaningful. Date and time are two small dimensions instead of one dimension per minute of the whole year. `transaction_ts` must stay in the fact because the join
   to `dim_product` history needs the exact time; `date_key` and `time_key` cannot replace it.
2. **Keep personal data in `dim_employee`** (`salary`, `address`) for a later data security exercise, tagged `meta: {pii: true}`
   in YAML so a tag-based masking policy can be applied. (Date of birth and phone number are not included because the dashboard does not use them.)
3. **Line items without a promotion use the fixed member `-1` "No promotion"**, so the key in the fact is never empty. Add a member
   `-2` "Unknown" for keys not yet in the dimension (late-arriving data); the `-2` convention applies to every dimension.

Note carried to step 5: `salary` changes often. If it were a tracked column, every raise would create a new employee version. Only
`store_id` is tracked; `salary` is overwritten.

## Step 4. Facts

The fact table is `fct_sales`, one row per `completed` line item. All money and quantity measures are **additive**, except the two unit prices `regular_price`
and `unit_cost`. Ratios (gross margin, average transaction value) are **not stored in the fact**: they are defined as metrics in
Preset, for example `SUM(gross_profit) / SUM(net_amount)`, so nobody accidentally averages ratios.

**Keys and attributes in the fact:** `date_key`, `time_key`, `product_key`, `store_key`, `employee_key`, `payment_method_key`, `promotion_key`,
`transaction_id`, `line_number`, `transaction_ts`.

**Measures:**

| Measure | How it is derived | Additive |
|---|---|---|
| `quantity` | source | yes |
| `regular_price` | source (price at the time of sale) | no, it is a unit price |
| `unit_cost` | cost of the product version valid at `transaction_ts` | no, it is a unit price |
| `gross_amount` | `quantity × regular_price` | yes |
| `discount_amount` | promotion discount, formula below | yes |
| `coupon_amount` | source | yes |
| `net_amount` | `gross_amount − discount_amount − coupon_amount` | yes |
| `cost_amount` | `quantity × unit_cost` | yes |
| `gross_profit` | `net_amount − cost_amount` | yes |

### Additivity of measures

| Type | Meaning | In `fct_sales` |
|---|---|---|
| **Additive** | can be summed across every dimension, including time | `quantity`, `gross_amount`, `discount_amount`, `coupon_amount`, `net_amount`, `cost_amount`, `gross_profit` |
| **Semi-additive** | can be summed across every dimension except time (for example inventory balance: you can sum across stores, but not across days) | none |
| **Non-additive** | cannot be summed across any dimension | `regular_price`, `unit_cost` (unit prices); ratios are not additive either, but they are Preset metrics, not fact columns |

Having no semi-additive measures is deliberate: this type appears almost only in periodic snapshot facts, which this model does not have (inventory is
out of scope, see step 6). `fct_sales` is a transaction fact, so every money and quantity measure is fully additive.

Further reading: [Additive, Semi-Additive, and Non-Additive Facts](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/additive-semi-additive-non-additive-fact/).

### Promotion and coupon conventions

The source does not store the promotion discount amount (a line has only `promotion_id`) and does not say whether it applies per unit or per line, so the convention is settled here:

- **Promotions apply per unit**, multiplied by quantity:
  - percentage: `discount_amount = quantity × regular_price × amount / 100`
  - fixed amount: `discount_amount = quantity × MIN(amount, regular_price)`

  `MIN` keeps the discounted price from going negative. This matches the seed: fixed-amount promotions are only assigned to products with `unit_price >= amount × 4`, so the discount is always
  smaller than the unit price.
- **`coupon_amount` applies per line**, not multiplied by quantity. The seed assigns it once for the whole line.
- When editing `seed.py` or `stream.py`, keep both conventions.

### Cost is written into the fact at load time

`unit_cost` and `cost_amount` are written into the fact at load time. `unit_cost` must come from the **`dim_product` version valid at `transaction_ts`** (range join,
step 5), not from the current product in the silver layer. *If you use the current table:* it is correct at load time, but a full refresh would recompute all of history
with the new cost, which is exactly the bug SCD2 exists to prevent.

Why store it in the fact:
- Simple queries in Preset: gross profit is one `SUM` on the fact, not a time-range join every time the dashboard opens.
- Reported numbers are stable; a receipt is recomputed only when it is reloaded.
- Still traceable: `product_key` points to the exact product version, so checking `unit_cost` takes one join.

Known limitation: if the source corrects a past cost, the fact does not update unless a full refresh runs. Acceptable for a portfolio project.

**dbt tests:** `net_amount >= 0` and `discount_amount <= gross_amount`, catching cases where the generator or stream breaks the promotion convention.

## Step 5. Dimension types (SCD)

| Dimension | Type | Reason |
|---|---|---|
| `dim_date` | Type 0 | generated from a calendar, never changes |
| `dim_time` | Type 0 | 1,440 pre-generated minutes, never changes |
| `dim_product` | **Type 2** | cost and price change over time; needed for gross profit at the time of sale |
| `dim_employee` | **Type 2** | an employee's store changes; we need to know where they worked at the time of sale |
| `dim_store` | Type 1 | `stream.py` does not change stores; overwrite if the source corrects one |
| `dim_payment_method` | Type 1 | small lookup list, overwrite |
| `dim_promotion` | Type 1 | campaigns have fixed start and end dates; overwrite if the source corrects one (old receipts do not change, see below) |

Every dimension has a `-2` "Unknown" member; `dim_promotion` also has `-1` "No promotion" (step 3).

Further reading: [Type 2: Add New Row](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/),
[Dimension Surrogate Keys](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/dimension-surrogate-key/).

### Which columns create a new version (Type 2)

- **`dim_product`:** `unit_cost`, `unit_price`, `category_id`, `brand_id`. The product name is overwritten (Type 1) because it usually changes only to fix a typo.
  The source currently does not change category or brand, so tracking these two columns creates no extra versions; if a product changes category later, past
  revenue by category stays correct. The tracked column list is easy to change: history lives in RAW, so you only edit the code and run a dbt full refresh.
- **`dim_employee`:** only `store_id`. `salary` and the other columns are overwritten (Type 1) with the latest value because salary changes often, and every
  raise would create a useless version. Personal columns are tagged `meta: {pii: true}` (step 3).

### Building versions from RAW

Ingestion writes every changed `product` or `employee` row as a new row in RAW (same `id`, newer `updated_at`; see section 9.2 of
Project-Spec). SCD2 is built directly from those rows with window functions, **not with `dbt snapshot`**: RAW already keeps every version, a snapshot only adds
a copy of history that cannot be rebuilt, while window functions are **idempotent** (`dbt build --full-refresh` gives the same result no matter how many times
it runs). Both approaches have the same level of detail.

0. **Deduplicate in staging first.** The incremental cursor can reload rows that sit exactly on the boundary, so staging keeps exactly one row per combination of all business
   columns (including `updated_at`): `qualify row_number() over (partition by <all business columns> order by _dlt_load_id desc) = 1`.
1. Sort the rows of a business key by `updated_at`.
2. **Compare each row with the previous one using `LAG` and `IS DISTINCT FROM`**, keeping only rows where a tracked column changed. Do not use `DISTINCT` or group by
   value: the price sequence A → B → A must give 3 versions; grouping by value would merge the two A rows into one and the validity ranges would be wrong. `IS DISTINCT FROM` also handles `NULL` correctly.
3. `valid_from` is that row's `updated_at`; `valid_to` is the `valid_from` of the next version. The last version has `valid_to = '9999-12-31'` and `is_current = true`.
4. **The first version of each key has `valid_from = '1900-01-01'`.** The first row in RAW appears only at the first load, after all of the seed's historical
   transactions; using the real `updated_at` would leave the 100,000 seed orders matching no version.
5. **Type 1 columns must take the latest value of the key.** After step 2, columns like `salary` or `product_name` still carry the value at the time of that
   version, giving an "incomplete SCD2". Use `FIRST_VALUE(...) over (partition by id order by updated_at desc)` to write the latest value onto every version.

The actual code of `int_product_scd2` (trimmed to two tracked columns instead of four):

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
    WHERE prev_updated_at IS NULL                       -- first version
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

The dimension's surrogate key is a hash of the business key and the version's `valid_from` (the `surrogate_key` macro, which uses Snowflake's `HASH` function, so it is
a 64-bit integer). Boundary convention: `valid_from <= transaction_ts < valid_to`.

Consequences:
- **RAW is the only place that keeps history.** Never run dlt with `refresh="drop_sources"`, `drop_resources` or `replace` on `product` and `employee`:
  all SCD2 history would be lost.
- **`dim_promotion` is Type 1:** `discount_amount` is computed and written into the fact at load time, like `unit_cost`, so correcting a promotion does not change old receipts; they
  change only on a full refresh (same limitation as step 4).

### Joining the fact to a version

`fct_sales` joins `dim_product` and `dim_employee` on the business key (`product_id`, `employee_id`) and the range `valid_from <= transaction_ts < valid_to`.
The fact keeps `product_key` and `employee_key` pointing to the exact version.

Limitation (also in section 9.2 of Project-Spec): each `stream.py` cycle must be ingested before the next cycle, otherwise intermediate versions are lost.

## Step 6. Fact table type

| Type | Used for | Applied here |
|---|---|---|
| **Transaction fact** | each row is an event that happened at a point in time | **`fct_sales`** |
| Periodic snapshot | state at regular intervals (for example end-of-day inventory) | **`fct_store_headcount_monthly`** (staffing per store per month) |
| Accumulating snapshot | a process with several milestones, where the row is updated as each milestone passes (order → delivery → payment) | not used, the source has no multi-milestone lifecycle |
| Factless fact | records a relationship, with no measures | later: promotion coverage |

**`fct_sales` is a transaction fact.** Each line item is a sale event at `transaction_ts`, created once and never changed afterwards. Characteristics:
- atomic grain (step 2), additive measures (step 4), dense: every row has all measures;
- loaded incrementally by (`transaction_id`, `line_number`); receipts do not change after they are written, so deletes and updates need no handling;
- each row is tied to time through `date_key` and `time_key`, and keeps `transaction_ts` to join SCD2 versions (step 5). `date_key` and `time_key`
  are computed from local time (`Asia/Ho_Chi_Minh`), not UTC.

**`fct_store_headcount_monthly` is a periodic snapshot** (spec 004, Project-Spec §10.6). Business process: staffing
of a store. Grain: one store per calendar month, every month from January 2020, also when nothing happened. Measures:
- `opening_headcount`, `closing_headcount`: **semi-additive**, a level at a point in time. Sum them across stores, never
  across months; over a quarter the headcount is the closing headcount of its last month;
- `joiners`, `leavers`, `transfers_in`, `transfers_out`, `net_revenue`: additive (flows during the month);
- revenue per employee is not stored; it is the metric `SUM(net_revenue) / SUM(average_headcount)`.

It is dense (a row for every store-month), rebuilt in full each run, and carries `store_name` and `month_start` next to
`store_key` and `month_start_date_key` so the semantic layer and Preset read it without joins.

Other facts, built from the same source, come after `fct_sales` runs reliably:
- **`fct_sales_transaction`** (aggregate table, one row per receipt): basket value and average transaction value. Built from `fct_sales`, without changing the grain.
- **Promotion coverage** (factless fact): which products are on promotion but not selling. Built from `promotion_product` × `dim_date` between `start_date` and `end_date`.

These two extra facts stay in the docs until they are needed; they are not yet in section 10.2 of Project-Spec.

Further reading: [Transaction Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/transaction-fact-table/),
[Periodic Snapshot](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/periodic-snapshot-fact-table/),
[Accumulating Snapshot](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/accumulating-snapshot-fact-table/),
[Factless Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/factless-fact-table/).
