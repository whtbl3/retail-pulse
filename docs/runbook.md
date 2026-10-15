# Runbook: when the pipeline fails

What to do for each way the nightly `full_pipeline` can go wrong. Written for spec
[001-pipeline-operations](../specs/001-pipeline-operations/spec.md) (R8). The setup that runs the pipeline
is in [phases/10-operations.md](phases/10-operations.md).

## Never do these to recover

These delete Snowflake RAW, the only store of SCD2 history. No failure below is fixed by them:

- `make seed`, `make reseed`, `make db-reset`, `make clean-raw`.
- Changing `product` or `employee` in dlt to `replace`, `merge` or `refresh="drop_sources"`.
- Dropping or truncating a `RAW` table by hand in Snowflake.

## Where to look first

1. **Slack** `#all-retail-pulse-alerts`: the message names the job, the failed step, the first error line
   and the run link.
2. **Dagster UI** <http://localhost:3000>: open the run from the link, then the failed step's logs.
3. **Container logs** when the UI does not open: `make dagster-logs`.

No Slack message but you expected one? See [Alert did not arrive](#alert-did-not-arrive).

## Ingestion failed (step `retail_raw`)

**How you recognise it.** The run failed on `retail_raw` after two retries 5 minutes apart. The run page
shows three attempts. dbt did not run.

**Likely causes.**

- Postgres is down: `docker ps` does not list `retail-pulse-postgres`, or the error says
  `connection refused` on `postgres:5432`.
- Snowflake rejected the login: wrong key path in `.dlt/secrets.toml`, or the key was rotated.
- Snowflake warehouse suspended for a credit limit, or the network dropped for longer than the retries.

**Recovery.**

1. Fix the cause: `make up` for Postgres; check `.dlt/secrets.toml` against `.dlt/secrets.toml.example`.
2. Rerun from the UI: open the failed run, **Re-execute** > **From failure**. dlt keeps its incremental
   state, so the rerun loads only rows it has not loaded yet. Rows reloaded at the cursor boundary are
   dropped by staging.

## Great Expectations check failed (`great_expectations` on a `raw/*` asset)

**How you recognise it.** The run failed, the step `retail_raw` succeeded, and a `great_expectations`
check on one of the RAW assets is red. dbt did not run, because these checks are blocking.

**Find the failing rows.** Open the asset (for example `raw/sales_transaction_item`) > **Checks** >
`great_expectations`. The `failures` metadata lists each failed expectation, its column and the number
of bad rows, for example `sales_transaction_item: expect_column_values_to_be_between quantity 3 bad rows`.
`make quality` prints the same list from the terminal. Then query RAW in Snowflake with that column and
rule, for example `SELECT * FROM RETAIL_PULSE.RAW.SALES_TRANSACTION_ITEM WHERE quantity < 1`.

**Usual causes.** A change in the source: a new status value, a `NULL` the generator now writes, a
column added in `infras/postgres/init/01_schema.sql` without updating the check. Less often, a bug in
`stream.py` or `seed.py`.

**Rerun once fixed.**

1. Fix the source (the generator, or the row in Postgres). Fix the check in
   `src/retail_pulse/quality/raw_checks.py` only if the new value is correct.
2. Bad rows already in RAW stay there (RAW is append-only). A corrected row with a newer `updated_at`
   becomes the latest version, and staging uses the latest.
3. **Re-execute** > **From failure**. The check runs again before dbt.

## dbt model or test failed (step `retail_dbt_assets`)

**How you recognise it.** RAW loaded and its checks passed, but `retail_dbt_assets` failed. dbt runs
once and is never retried, because the same data gives the same failure.

**Recovery.**

1. Open the step logs: dbt prints the failing model or test, for example `not_null_fct_sales_product_key`.
2. Reproduce locally, in your dev schemas: `make dbt-build SELECT=<model>+`.
3. Fix the model or test through a pull request; CI runs dbt slim CI on it.
4. After the merge: `git pull`, `make dagster-up` (rebuilds the image), then **Re-execute** > **From
   failure**.

## `fct_sales` has `-2` keys

**How you recognise it.** No test fails, because every dimension has a `-2` "Unknown" member. The
dashboard shows "Unknown" products, stores or employees, or this query returns more than zero:
`SELECT COUNT(*) FROM RETAIL_PULSE.MARTS.FCT_SALES WHERE product_key = -2 OR employee_key = -2`.
Sales arrived before their dimension version.

**Recovery.** Run the job `fct_sales_full_refresh` from the UI (or `make dbt-full-refresh`). It rebuilds
`fct_sales` only and never touches RAW (spec §17).

## RAW is stale (freshness warning)

**How you recognise it.** A yellow `freshness` check on `raw/sales_transaction`, `raw/sales_transaction_item`,
`raw/product` or `raw/employee`. The run still succeeds; this is a warning only. The metadata shows
`hours_since_newest_row` and `dbt_status` (`warn` after 26 hours, `error` after 3 days).

**Usual causes.**

- No new sales in Postgres: nothing ran `stream.py --sales` today. Expected in this project.
- `product` and `employee` only change when the simulator runs, so they warn on quiet days. Not an error.
- Ingestion succeeded but loaded nothing because the source `updated_at` stopped moving: check the
  trigger `trg_<table>_updated_at` in Postgres.

**Recovery.** Generate data if needed (`make stream-sales`) and let the next run load it. Do not force a
full reload.

## Dagster is down

**How you recognise it.** <http://localhost:3000> does not answer, or the 23:00 run did not start.

**Recovery.**

1. `docker ps`: are `retail-pulse-dagster-webserver` and `retail-pulse-dagster-daemon` up? After a machine
   restart they come back when Docker starts. If not: `make dagster-up`.
2. `make dagster-logs` shows why the daemon stopped (a code error at load time, or Postgres down).
3. Missed the 23:00 run: start `full_pipeline` by hand from the UI. A missed schedule is not run twice.
4. Two runs at 23:00: `make dagster` (dev mode) was also running. Stop it; keep one scheduler.

## Alert did not arrive

- `SLACK_WEBHOOK_URL` is empty or missing in `.env`: the sensor logs
  `SLACK_WEBHOOK_URL is not set; no notification sent` in the sensor's tick log (UI > **Automation** >
  `slack_on_run_failure`). Add it, then `make dagster-up`.
- `Slack alert not sent: HTTPError` in the same log: the webhook was revoked. Create a new one in the
  Slack app (**Incoming Webhooks**) and replace it in `.env`.
- Test the webhook without Dagster:
  `set -a && . ./.env && set +a && curl -s -X POST -H 'Content-type: application/json' --data '{"text":"test"}' "$SLACK_WEBHOOK_URL"`
  should print `ok`.

A failed alert never changes the run's own status.
