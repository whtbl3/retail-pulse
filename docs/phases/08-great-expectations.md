# Phase 8: Great Expectations (RAW quality checks)

Goal: stop bad data **right at RAW**, before dbt runs. Great Expectations (GE) complements dbt tests, it does not
replace them: dbt tests remain the main quality mechanism.

## Why it is needed when there are already 148 dbt tests

dbt tests check **after** a model is built. If RAW has bad rows (empty keys, unknown statuses, negative quantities),
dbt still builds and can produce wrong numbers without any warning. GE checks RAW and, in Dagster, **blocks dbt from
running** when RAW fails.

| | dbt test | Great Expectations |
|---|---|---|
| Where it checks | staging, intermediate, marts | RAW |
| When | after the model is built | before dbt runs |
| On failure | the model is already built | downstream dbt does not run |

GE **does not repeat** what dbt already does: no `unique` or `relationships` checks, because RAW is append-only, so
duplicates are normal, and staging already dedups.

## What was built

Code: `src/retail_pulse/quality/raw_checks.py`. It checks the 4 incrementally loaded tables (the most likely to get dirty):

| RAW table | Checks |
|---|---|
| `sales_transaction` | has rows; key columns, `transaction_ts`, `updated_at` not null; `status` in `completed`, `cancelled`, `returned` |
| `sales_transaction_item` | has rows; key, `product_id`, `quantity`, `regular_price` not null; `quantity >= 1`; `regular_price >= 0`; `coupon_amount >= 0` |
| `product` | has rows; `id`, `product_sku`, price, unit cost, `updated_at` not null; `unit_price >= 0`; `unit_cost >= 0` |
| `employee` | has rows; `id`, `store_id`, `updated_at` not null; `salary >= 0` |

- Reads as the `DBT_TRANSFORMER` user (role `TRANSFORMER`, only `SELECT` on RAW), using the same environment variables
  as dbt (`SNOWFLAKE_ACCOUNT`, `DBT_PRIVATE_KEY_PATH`).
- **In Dagster:** `src/retail_pulse/orchestration/quality_checks.py` creates one **asset check** per table, named
  `great_expectations`, with `blocking=True`. If a check fails, the downstream assets (dbt) in the same run do not run.
- **Manual run:** `make quality` (exits with code 1 on failure and prints each failed check).

Further reading: [GX Core introduction](https://docs.greatexpectations.io/docs/core/introduction/),
[Dagster: asset checks](https://docs.dagster.io/guides/test/asset-checks).

## Technical decisions

- **No GE Snowflake datasource.** It needs `snowflake-sqlalchemy`, which forces `sqlalchemy` down from 2.1 to 2.0
  (the project pins `sqlalchemy>=2.1.2`). Instead, tables are read into pandas and passed to GE: no dependency changes.
- **Limit:** whole tables are pulled into RAM. That is fine at a few hundred thousand rows (RAW is about 290 thousand
  rows now). At tens of millions of rows, the checks must be pushed into Snowflake or run on a sample. This limit is
  noted in the code.
- Only the columns being checked are selected, and numeric types are cast to `float` in SQL, because Snowflake returns
  `NUMBER` as `Decimal`.

## Verification

- `make quality`: all 4 tables `OK` on the current data.
- `tests/test_raw_checks.py`: clean data passes; data with empty keys and `status = 'refunded'` is caught. This proves
  the checks really detect errors and are not always "green".
- Running the `full_pipeline` job: all 4 `great_expectations` checks `passed`, then dbt finished, `RUN_SUCCESS`.
- When dlt fails (Postgres stopped): the 4 checks and dbt are all skipped, because their dependency `retail_raw` failed.

**Not yet verified:** blocking dbt when a GE check itself fails. RAW has not been dirtied on purpose, because RAW is
append-only and is never edited by hand. `blocking=True` is a Dagster feature, but it needs one real test to be sure.

## Adding a new check

Edit the `TABLES` dict in `raw_checks.py`: add a `gxe.Expect...` to the table's list. For a new table, add an entry
(a `SELECT` of the columns to check and a list of checks). The Dagster asset check follows `TABLES` automatically.

Next: [Phase 9: CI/CD](09-dataops-ci.md).
