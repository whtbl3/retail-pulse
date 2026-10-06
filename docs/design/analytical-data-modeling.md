# Analytical Data Modeling

The analytical (Kimball) model for the warehouse, built from the source described in
[operational-data-modeling.md](operational-data-modeling.md). It is designed step by step, and each
step is approved before the next one starts.

| Step | Content | Status |
|---|---|---|
| 1 | Identify the business process | Approved |
| 2 | Clarify the grain | Approved |
| 3 | Identify the dimensions | Approved |
| 4 | Identify the facts | Approved |
| 5 | Choose the dimension types (Type 0/1/2...) | Approved |
| 6 | Choose the fact table type (transaction / periodic snapshot / accumulating) | Approved |

## Step 1. Business process

**Point-of-sale (POS) checkout sales.** This is the `Buy` event in the conceptual model and the only
source that carries price, quantity, promotion, store, cashier, payment method and time together.

The business questions this process must answer (from the problem statement in the README):

- revenue and trends over time;
- performance by product, category and brand;
- performance by store (and cashier);
- promotion effectiveness;
- gross profit over time, using the cost that was valid at the time of sale.

Promotions are not a separate process. In the source a promotion is context for a line item (a
dimension attached to the fact), not an event with its own time and measures. A "promotion coverage"
model (factless fact built from `promotion_product` × date) can be added once the main fact works.

Out of scope for this process: inventory (`Stocks`), returns and cancellations (only `completed`
transactions are analyzed, see Project-Spec section 7.3).

## Step 2. Grain

**One row per invoice line, i.e. per `sales_transaction_item`
(`transaction_id`, `line_number`), `completed` transactions only.**

Reason: this is the smallest level of detail in the source, so every question from step 1 can be
aggregated from it without losing information. Consequences:

- `transaction_id` lives in the fact as a degenerate dimension; invoice-level metrics (basket size,
  average invoice value) come from an aggregate mart built on this fact, not from a different grain;
- invoice attributes (store, cashier, payment method, time) repeat on every line of the same
  invoice, so invoices must be counted with `COUNT(DISTINCT transaction_id)`;
- the source stores `regular_price` at the time of sale on the line, but **not the cost**; cost only
  exists in `product.unit_cost`, which changes over time. A correct gross profit needs the `product`
  version that was valid at the time of sale (decided in steps 3 and 5).

**Transaction status (decided):** the fact contains only `completed` transactions, has no status
column and does no return analysis. An order changing status after it was loaded (for example
`completed` to `returned`) is out of scope: invoices are treated as unchanged once written.

## Step 3. Dimensions

Each dimension answers "who, what, where, when, how" for a line item. With the grain from step 2
there are 7 dimensions and 2 degenerate dimensions. The SCD type of each dimension is decided in
step 5.

| Dimension | Answers | Source | Proposed attributes |
|---|---|---|---|
| `dim_date` | When (date) | generated from the calendar, not in the source | date, year, quarter, month, week, weekday, weekend flag |
| `dim_time` | When (time of day) | pre-generated, 1,440 rows (one per minute) | hour, minute, day part (morning/noon/afternoon/evening) |
| `dim_product` | What was sold | `product` + `category` + `brand` | SKU, name, category, brand, price, cost |
| `dim_store` | Where | `store` (via `sales_transaction.store_id`) | store name, address, phone number |
| `dim_employee` | Which cashier | `employee` | name, current store, start date, end date |
| `dim_payment_method` | How it was paid | `payment_method` | method name |
| `dim_promotion` | Which promotion | `promotion` | type (percentage or fixed amount), value, start date, end date, display label |

Degenerate dimensions (stored directly in the fact, no table of their own): `transaction_id` and
`line_number`.

Points derived from the source:

- **Category and brand are folded into `dim_product`** (star schema, not snowflake). The source
  separates them only to reach 3NF; the analytical model does not need that.
- **The store of the invoice differs from the store of the employee.** `sales_transaction.store_id`
  is where the sale happened; `employee.store_id` is where the employee currently works and can
  change. The fact keeps the `dim_store` key of the invoice; the employee's store is only an
  attribute of `dim_employee`.
- **`dim_product` holds cost and price**, because they change over time and are the reason history
  is needed (step 2).
- **There is no dimension for transaction status**, because the fact only holds `completed` and
  status changes after loading are out of scope (see step 2).
- **`dim_promotion` has no name** because the source has no name column, so a display label is
  generated from the type and value (for example "Giảm 10%", "Giảm 20.000đ", i.e. "10% off",
  "20,000đ off").

Decisions made:

1. **Add `dim_time` and keep `transaction_ts` in the fact.** The seed generates sale times from 07:00
   to 21:00 with a peak around 18:00, so analysis by time band is meaningful. Date and time are two
   small dimensions instead of one dimension per minute of the whole year. `transaction_ts` must
   stay in the fact because joining to the history of `dim_product` needs the exact time;
   `date_key` + `time_key` cannot replace it.
2. **Keep personal data in `dim_employee`** (date of birth, address, phone number, salary) to be
   used later for data security exercises. When writing dbt, tag these columns with
   `meta: {pii: true}` in the YAML so masking policies can be applied by tag later.
3. **Line items without a promotion use the fixed member `-1` "No promotion"**, so the key in the
   fact is never null. Add a member `-2` "Unknown" for keys that are not yet in the dimension
   (late-arriving data); the same `-2` convention applies to the other dimensions.

Note carried to step 5: `salary` changes often. If it were a tracked column, every raise would
create a new employee version. Only `store_id` should be tracked; `salary` is overwritten.

## Step 4. Facts

The fact is `fact_sales`, with one `completed` invoice line per row. All money and quantity measures
are additive except the two unit prices, `regular_price` and `unit_cost`. Ratios (gross margin,
average invoice value) are not stored in the fact; they are defined as metrics in Preset, for
example `SUM(gross_profit) / SUM(net_amount)`, so nobody averages ratios by accident.

**Keys and attributes in the fact:** `date_key`, `time_key`, `product_key`, `store_key`,
`employee_key`, `payment_method_key`, `promotion_key`, `transaction_id`, `line_number`,
`transaction_ts`.

**Measures:**

| Measure | How it is obtained | Additive |
|---|---|---|
| `quantity` | source | yes |
| `regular_price` | source (price at the time of sale) | no, unit price |
| `unit_cost` | cost of the product version valid at `transaction_ts` | no, unit price |
| `gross_amount` | `quantity × regular_price` | yes |
| `discount_amount` | promotion discount, formula below | yes |
| `coupon_amount` | source | yes |
| `net_amount` | `gross_amount − discount_amount − coupon_amount` | yes |
| `cost_amount` | `quantity × unit_cost` | yes |
| `gross_profit` | `net_amount − cost_amount` | yes |

### Promotion and coupon conventions

The source does not store the discount amount of a promotion (a line only has `promotion_id`) and
does not say whether it applies per unit or per line, so the following convention is fixed here:

- **A promotion applies per unit**, multiplied by the quantity:
  - percentage: `discount_amount = quantity × regular_price × amount / 100`
  - fixed amount: `discount_amount = quantity × MIN(amount, regular_price)`

  `MIN` prevents the discounted price from going negative. This matches the seed: fixed-amount
  promotions are only assigned to products with `unit_price >= amount × 4`, so the discount is
  always smaller than the price of one unit.
- **`coupon_amount` applies per line**, not multiplied by the quantity. The seed assigns it once for
  the whole line.
- When changing `seed.py` or `stream.py`, both conventions must be preserved.

### Cost is written to the fact at load time

`unit_cost` and `cost_amount` are written to the fact at load time. `unit_cost` must come from the
**`dim_product` version valid at `transaction_ts`** (range join, step 5), not from the current
product in the silver layer: using the current table is correct at load time, but a full refresh
would recompute the whole history with the new cost, which is exactly the error SCD2 exists to
avoid.

Why store it in the fact:

- Preset queries stay simple: gross profit is a `SUM` on the fact, with no time-range join every
  time a dashboard opens.
- Reported numbers stay stable; an invoice is only recomputed when it is loaded again.
- It is still traceable: `product_key` points to the exact product version, so `unit_cost` can be
  cross-checked with a join.

Known limit: if the source corrects a cost in the past, the fact does not update unless a full
refresh runs. That is acceptable for a portfolio project.

### Data tests (dbt)

`net_amount >= 0` and `discount_amount <= gross_amount`. These two tests catch the generator or the
stream violating the promotion convention.

## Step 5. Dimension types (SCD)

| Dimension | Type | Reason |
|---|---|---|
| `dim_date` | Type 0 | generated from the calendar, never changes |
| `dim_time` | Type 0 | pre-generated 1,440 minutes, never changes |
| `dim_product` | **Type 2** | cost and price change over time and are needed for gross profit at the time of sale |
| `dim_employee` | **Type 2** | the employee's store changes, and we need to know where they worked at the time of sale |
| `dim_store` | Type 1 | `stream.py` does not change stores; overwritten if the source corrects them |
| `dim_payment_method` | Type 1 | small lookup, overwritten |
| `dim_promotion` | Type 1 | a program has fixed start and end dates; overwritten if the source corrects it (old invoices stay unchanged, see below) |

Every dimension has a `-2` "Unknown" member; `dim_promotion` also has `-1` "No promotion" (step 3).

### Which columns create a new version (Type 2)

- **`dim_product`:** `unit_cost`, `unit_price`, `category_id`, `brand_id`. The product name is
  overwritten (Type 1), because it usually only changes when a typo is fixed. The source does not
  currently change category or brand, so tracking those two columns creates no extra versions; if a
  product later changes category, past revenue by category stays correct. The list of tracked
  columns is cheap to change: history lives in RAW, so it is enough to edit the code and run a dbt
  full refresh.
- **`dim_employee`:** only `store_id`. `salary` and the other columns are overwritten (Type 1) with
  the latest value, because salary changes often and every raise would create an unnecessary
  version. Personal columns are tagged `meta: {pii: true}` (step 3).

### How versions are built from RAW

Ingestion writes each changed `product` or `employee` row as a new row in RAW (same `id`, newer
`updated_at`; see Project-Spec section 9.2). SCD2 is built directly from those rows with window
functions, without `dbt snapshot`: RAW already holds every version, a snapshot would only add a
second copy of history that cannot be rebuilt, while window functions are idempotent (`dbt build
--full-refresh` gives the same result no matter how many times it runs). Both approaches have the
same level of detail.

0. **Staging deduplicates first.** The incremental cursor can reload rows right at the boundary, so
   staging keeps one row per (`id`, `updated_at`):
   `qualify row_number() over (partition by id, updated_at order by _dlt_load_id desc) = 1`.
1. Order the rows of one business key by `updated_at`.
2. **Compare each row with the previous one using `LAG` and `IS DISTINCT FROM`**, and keep only the
   rows where a tracked column changed. Do not use `DISTINCT` or group by value: a price sequence
   A → B → A must produce 3 versions, and grouping would merge the two A's and make the validity
   interval wrong. `IS DISTINCT FROM` also handles `NULL` correctly.
3. `valid_from` = `updated_at` of that row; `valid_to` = `valid_from` of the next version. The last
   version has `valid_to = '9999-12-31'` and `is_current = true`.
4. **The first version of each key has `valid_from = '1900-01-01'`.** The first row in RAW only
   appears at the first ingest, after all the seed's historical transactions; with the real
   `updated_at`, the 100,000 seeded orders would not match any version.
5. **Type 1 columns must take the latest value of the key.** After step 2, columns such as `salary`
   or `product_name` still carry the value at the time of the version row, which makes them an
   "incomplete Type 2". Join with the latest row of the key and overwrite these columns on every
   version.

Template for `dim_employee` (`dim_product` uses the same template, with the comparison changed to
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
    l.first_name, l.last_name, l.salary, l.end_date,      -- Type 1: latest value
    case when row_number() over (partition by v.id order by v.updated_at) = 1
         then '1900-01-01'::timestamp_tz else v.updated_at end as valid_from,
    coalesce(lead(v.updated_at) over (partition by v.id order by v.updated_at),
             '9999-12-31'::timestamp_tz) as valid_to,
    valid_to = '9999-12-31'::timestamp_tz as is_current
from versions v
join latest l on l.id = v.id
```

Surrogate key of the dimension: a hash of the business key and the `updated_at` of the version.
Boundary convention: `valid_from <= transaction_ts < valid_to`.

Consequences:

- **RAW is the only place that holds history.** Never run dlt with
  `refresh="drop_sources"`/`drop_resources` or `replace` on the `product` and `employee` tables,
  because all SCD2 history would be lost.
- **`dim_promotion` is Type 1:** `discount_amount` is computed and written to the fact at load time,
  like `unit_cost`, so correcting a promotion leaves old invoices unchanged; they only change on a
  full refresh (the same limit as in step 4).

### Joining the fact to a version

`fact_sales` joins `dim_product` and `dim_employee` on the business key (`product_id`,
`employee_id`) and the interval `valid_from <= transaction_ts < valid_to`. The fact keeps
`product_key` and `employee_key` pointing to the exact version.

Limit (also in Project-Spec section 9.2): every `stream.py` cycle must be ingested before the next
cycle, otherwise intermediate versions are lost.

## Step 6. Fact table type

| Type | Used for | Applies here |
|---|---|---|
| **Transaction fact** | each row is an event that happened at one point in time | **`fact_sales`** |
| Periodic snapshot | state at regular intervals (for example end-of-day inventory) | not used, inventory is out of scope |
| Accumulating snapshot | a process with several milestones, where the row is updated as it passes each one (order → shipment → payment) | not used, the source has no multi-milestone lifecycle |
| Factless fact | records a relationship, no measures | later: promotion coverage |

**`fact_sales` is a transaction fact.** Each line item is a sale event at `transaction_ts`, created
once and unchanged afterwards. Characteristics:

- atomic grain (step 2), additive measures (step 4), dense: every row has all its measures;
- loaded incrementally by (`transaction_id`, `line_number`); orders do not change after being
  written, so no delete or update handling is needed;
- each row is tied to time through `date_key` and `time_key`, and keeps `transaction_ts` to join SCD2
  versions (step 5).

Other facts, built from the same source as `fact_sales`, to be done once `fact_sales` works:

- **`fact_sales_transaction`** (aggregate mart, one invoice per row): basket size and average
  invoice value. Built from `fact_sales`, without changing the grain of `fact_sales`.
- **Promotion coverage** (factless fact): which products are on promotion but not selling. Built
  from `promotion_product` × `dim_date` between `start_date` and `end_date`.

The two additional facts stay in this document until they are needed; they are not yet in
Project-Spec section 10.2.
