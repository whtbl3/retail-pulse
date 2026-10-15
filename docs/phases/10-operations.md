# Phase 10: Operations (always-on Dagster, retries, freshness, alerts)

Goal: the nightly pipeline runs on its own, keeps its history, retries what is safe to retry, warns when
RAW stops getting data, and tells you on Slack when a run fails. Spec:
[001-pipeline-operations](../../specs/001-pipeline-operations/spec.md). What to do when something
fails: [runbook.md](../runbook.md).

## Why it is needed

Until phase 9, Dagster ran only while `make dagster` was open in a terminal. Close the laptop lid and
the 23:00 run never happens; restart it and the run history is gone. A failed run was only visible to
someone who opened the UI, and the `freshness` rule on `sales_transaction` was never evaluated.

## What runs where

```text
make dagster-up
   │
   ├── retail-pulse-postgres           OLTP data + a `dagster` database for run history
   ├── retail-pulse-dagster-webserver  UI at http://localhost:3000
   └── retail-pulse-dagster-daemon     23:00 schedule, failure sensor, executes every run
```

| Piece | Where | Does |
| --- | --- | --- |
| `Dockerfile` | repo root | One image for both Dagster services: `uv sync --frozen`, then `dbt deps` and `dbt parse` so `manifest.json` is inside |
| `infras/dagster/dagster.yaml` | copied into the image | Run, event and schedule storage in the `dagster` Postgres database; one run at a time |
| `infras/dagster/workspace.yaml` | copied into the image | Loads `retail_pulse.orchestration.definitions` |
| `infras/docker-compose.yml` | | `dagster-webserver` and `dagster-daemon`, both `restart: unless-stopped` |
| `src/retail_pulse/orchestration/dlt_assets.py` | | Ingestion retries 2 times, 5 minutes apart |
| `src/retail_pulse/orchestration/freshness.py` | | Freshness check on the 4 incremental RAW tables |
| `src/retail_pulse/orchestration/alerts.py` | | Slack message when a run fails |

## Running

Once, in `.env` (see `.env.example`):

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   # Slack app > Incoming Webhooks; a secret
DAGSTER_BASE_URL=http://localhost:3000                    # base of the run link in the message
```

Then:

```bash
make dagster-up      # build the image, create the `dagster` DB if missing, start both services
make dagster-logs    # follow the logs
make dagster-down    # stop them; history stays in Postgres
```

After `git pull`, run `make dagster-up` again: it rebuilds the image with the new code.

`make dagster` (dev mode, reloads code on save) still works for development. Stop the Docker services
first: both use port 3000, and two schedulers would both fire at 23:00.

### Secrets stay outside the image

`.dockerignore` keeps `.env`, `.dlt/`, `.snowflake/`, `*.p8` and `profiles.yml` out of the build. At run time
Compose mounts them read-only:

| On your machine | In the container |
| --- | --- |
| `.env` | environment variables (`env_file`); `PG_HOST` is overridden to `postgres` |
| `.dlt/secrets.toml` | `/app/.dlt/secrets.toml` |
| `.snowflake/` | the same absolute path as on your machine, so `DBT_PRIVATE_KEY_PATH` works unchanged |
| `~/.dbt/` (or `DBT_PROFILES_DIR`) | `/run/dbt-profiles` |

The Makefile passes `REPO_DIR` for that `.snowflake/` mount, so run Compose through `make`. A bare
`docker compose` stops with `run docker compose through make`.

## Retries: only ingestion

`dlt_assets` has no `retry_policy` argument, so the asset asks for the retry itself:

```python
try:
    yield from dlt_res.run(context=context)
except Exception as exc:
    raise RetryRequested(max_retries=2, seconds_to_wait=300) from exc
```

A dropped connection to Postgres or Snowflake is often back after a few minutes. A rerun is safe: dlt
keeps its incremental state, and staging drops rows reloaded at the cursor boundary. dbt and the Great
Expectations checks are never retried, because the same data fails the same way.

## Freshness: warn, never block

The limits live in `dbt/models/staging/___sources.yml`, on `updated_at` for `sales_transaction`,
`sales_transaction_item`, `product` and `employee`: warn after 26 hours, error after 3 days. In Dagster a
`multi_asset_check` runs `dbt source freshness` once after RAW is loaded and reports one `freshness`
check per table. Both dbt levels show as a yellow warning, and the check is non-blocking, so dbt still
builds what did arrive.

`product` and `employee` change only when the simulator runs, so they warn on quiet days. That is
expected.

## Failure alert

`slack_on_run_failure` is a `run_failure_sensor` on `full_pipeline` and `fct_sales_full_refresh`. It is on by
default and posts:

```text
:red_circle: full_pipeline failed
Step: retail_dbt_assets
Error: dagster_dbt.errors.DagsterDbtCliRuntimeError: The dbt CLI process with command
Run: http://localhost:3000/runs/21badfea-...
```

Without `SLACK_WEBHOOK_URL` it logs `SLACK_WEBHOOK_URL is not set; no notification sent` in the sensor's tick
log and returns. A Slack error is logged without the URL and never raised. The alert can never fail a run.

## Verify

| Check | How | Spec |
| --- | --- | --- |
| UI survives closing the terminal | `make dagster-up`, close the terminal, open <http://localhost:3000> | AC1 |
| History survives a restart | Run a job, `docker restart retail-pulse-dagster-webserver retail-pulse-dagster-daemon`, the run is still listed | AC2 |
| Schedule runs unattended | **Automation**: `full_pipeline_schedule` Running, next tick 23:00 `Asia/Ho_Chi_Minh` | AC3 |
| Retry, freshness, alert | `make test` (`tests/test_operations.py`) | AC4 to AC8 |
| Slack works | Run `fct_sales_full_refresh` with Snowflake unreachable; one message arrives | AC7 |

## Errors encountered

| Error | Cause | Fix |
| --- | --- | --- |
| `(psycopg.OperationalError) the connection is closed` in the UI, `syntax error at or near "$1"` in the daemon | SQLAlchemy 2.1 uses psycopg 3 for `postgresql://`; dagster-postgres needs psycopg2 | `scheme: postgresql+psycopg2` in `dagster.yaml` |
| `required variable REPO_DIR is missing a value` | `docker compose` was run directly | Use `make dagster-up` |
