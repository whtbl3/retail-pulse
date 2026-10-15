# Phase 4: Source change simulator (`stream.py`)

## Why it is needed

Real data does not stand still: prices change, employees move between stores, new receipts keep arriving. If the source
only had a static dataset, you could not test the two most important parts of the project: **SCD2** (history of price
changes and store transfers) and **incremental** (loading only new data). `stream.py` creates those small, realistic changes.
Without it, every product and employee would have a single version in RAW, the SCD2 models in phase 5 would have
nothing to track, and the incremental path of `fct_sales` would never see a new row.

Detailed design: [design/data-generator.md](../design/data-generator.md) (Part 2).

By default `stream.py` **only runs UPDATEs**: `unit_cost` and `unit_price` of existing products, and `store_id` of
current employees (empty `end_date`). No INSERT, no DELETE, and it never sets `updated_at` itself (the DB trigger does that).
With `--sales N`, each cycle also **INSERTs N new sales transactions** (see "Extra sales").

## Concepts

| Term | Meaning here |
|---|---|
| Cycle | One run of changes: a few products repriced, employees transferred, optional new sales, committed as one DB transaction |
| Version | One state of a product or employee. Each ingested change adds a row in RAW with the same `id` and a newer `updated_at` |
| SCD Type 2 | Slowly changing dimension that keeps every version with a validity range, built by dbt in phase 5 |
| Type 2 column | A column whose change creates a new version. `stream.py` changes `unit_cost` and `unit_price` of products and `store_id` of employees; the full list is in phase 5 |
| Store transfer | Changing an active employee's `store_id` to a different store, so sales are credited to the right store over time |
| Watermark | The highest `updated_at` dlt has already loaded. New sales from `--sales` must be timed after it, or they are never loaded |

## Run

```bash
make stream                       # 1 cycle, then exit
make stream-loop                  # run continuously, Ctrl+C to stop
uv run stream --seed 42           # reproducible choices and values
uv run stream --help              # show every option and default
```

| Option | Default | Meaning |
|---|---|---|
| `--products` | 5 | Number of products changed per cycle |
| `--cost-pct-min` / `--cost-pct-max` | 0.01 / 0.05 | Range of the unit cost change (up or down) |
| `--price-probability` | 0.10 | Probability that a chosen product also gets a selling price change |
| `--price-pct-min` / `--price-pct-max` | 0.01 / 0.08 | Range of the selling price change |
| `--sales` | 0 (off) | Number of new sales transactions INSERTed per cycle |
| `--transfers` | 1 | Number of employees moved per cycle (always to a different store), 0 = off |
| `--loop` / `--interval` | off / 30 seconds | Run continuously |
| `--seed` | none | Random seed |

Each cycle is one DB transaction: everything succeeds or everything rolls back. Connection or constraint errors return
a non-zero exit code. If the `product` table is empty, it reports "run `make seed` first".

```text
[cycle 1] product 13 SKU-00013: cost 108300 -> 110400, price 162000 -> 162000 (supplier_cost_adjustment)
[cycle 1] product 326 SKU-00326: cost 32100 -> 30800, price 46000 -> 44000 (price_revision)
[cycle 1] scanned 500, planned 5, updated 5 products
```

## Extra sales (`--sales N`)

```bash
make stream-sales             # 1 cycle: change prices, move employees, add SALES=300 transactions
make stream-sales SALES=50
uv run stream --sales 100 --products 3
```

*Why it is needed:* plain `stream` only changes existing data, so it adds no rows to the fact. To test the whole dlt and
dbt chain and the incremental part of `fct_sales`, the source needs **real new transactions**.

Generation reuses the exact sales rules of `seed.py` (per-unit promotions, per-line coupons, 95% completed, 2%
cancelled, 3% returned):
1. **Time window:** from the latest timestamp in `sales_transaction` (the larger of `transaction_ts` and `updated_at`)
   to now. The start must be **after** the dlt load watermark. Otherwise the new transactions will never be loaded.
2. **Opening hours:** only the part within 7:00–22:00 (`Asia/Ho_Chi_Minh` time) is used. Closed hours are skipped.
3. **Store and employee:** a random store with current employees; the employee belongs to the **current** store
   (including right after `stream` moved them).
4. **Price:** `regular_price` is the current selling price. Sales happen **before** price changes in the same cycle, so
   a price change only applies to later transactions.
5. The whole batch is written in one DB transaction.

If no opening hours have passed since the latest transaction (for example, a second run during the night), the command
logs "no opening hours since the latest transaction..." and sells nothing. The number of transactions per cycle is fixed by `--sales`,
and the timestamps are not concentrated in the evening as in `seed.py`.

## Limit: ingest after every cycle

```text
make stream  ->  new product.updated_at  ->  make ingest (append)  ->  dbt SCD2 (phase 5)
```

The `updated_at` cursor only sees the **final state** of a row at ingest time. So each cycle must be ingested before
the next cycle runs. *If skipped:* two price changes in a row leave only one version in RAW. The intermediate version is
lost forever and SCD2 misses a piece of history. The source also has no DELETE, because the cursor cannot see deleted rows.

## Check

```sql
SELECT id, product_sku, unit_cost, unit_price, updated_at
FROM retail.product ORDER BY updated_at DESC LIMIT 10;
```

Automated tests: `tests/test_stream.py` (see [Testing](../design/data-generator.md#testing)).

## Further reading

- [Kimball: SCD Type 2](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/):
  why each change is stored as a new row.

Next: [Phase 5: dbt](05-dbt.md).
