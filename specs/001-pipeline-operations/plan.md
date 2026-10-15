# 001: Pipeline operations, plan

Spec: [spec.md](spec.md)

## Approach

**Always-on Dagster (R1 to R3).** Add a `Dockerfile` that installs the project with `uv sync --frozen`
and two Compose services built from it: `dagster-webserver` (port 3000) and `dagster-daemon` (runs the
schedule and sensors). Both use `restart: unless-stopped` and read a checked-in `infras/dagster/dagster.yaml`
that puts run, event and schedule storage in a `dagster` database on the existing Postgres container.
`make dagster-up` creates that database if it is missing (an existing `pgdata` volume never reruns init
scripts), then starts the services; `make dagster-down` stops them. `make dagster` (dev mode) is unchanged.

Inside the containers Postgres is reached as `postgres`, not `localhost`, so Compose overrides `PG_HOST`.
Secrets are mounted read-only at run time, never copied into the image (R9): `.env` through `env_file`,
`.dlt/secrets.toml`, `.snowflake/` and the dbt `profiles.yml` folder as volumes. `.dockerignore` keeps
them out of the build context.

**Retry (R4).** `dlt_assets` has no `retry_policy` argument, so the dlt asset body catches a failure and
raises `RetryRequested(max_retries=2, seconds_to_wait=300)`. Only that op retries; the dbt op and the
Great Expectations checks keep the default of no retry.

**Freshness (R5).** The four incremental RAW tables get `loaded_at_field: updated_at` with
`warn_after: 26 hours` and `error_after: 3 days` in `dbt/models/staging/___sources.yml` (the existing
1 day / 3 days rule on `sales_transaction` is replaced). That file stays the single place the limits
live. A Dagster `multi_asset_check` on the four RAW assets runs `dbt source freshness` once, reads
`target/sources.json`, and reports one non-blocking check per table: passed when fresh, failed with
severity WARN when stale (warn or error), with the newest row's age in the metadata. Because it is
non-blocking, dbt still runs (AC6).

**Failure alert (R6, R7).** A `run_failure_sensor` on `full_pipeline` and `fct_sales_full_refresh`
posts to the Slack incoming webhook in `SLACK_WEBHOOK_URL`, using the standard library (`urllib`), so no
new dependency. The message has the job name, failed step, first line of the error and a link built
from `DAGSTER_BASE_URL` (default `http://localhost:3000`). Without the variable, it logs one line and
returns. A Slack error is logged and never raised, so the alert cannot fail anything (R7).

**Runbook (R8).** `docs/runbook.md`: one section per failure type (ingestion, Great Expectations
check, dbt test, stale RAW, `-2` keys in `fct_sales`, Dagster down), each with how to recognise it,
likely causes, recovery steps, and the steps that are never allowed (`make seed`, `clean-raw`,
`replace` on RAW).

## Files

| File | Change |
| --- | --- |
| `Dockerfile`, `.dockerignore` | New: image for Dagster webserver and daemon |
| `infras/docker-compose.yml` | Add `dagster-webserver` and `dagster-daemon` services |
| `infras/dagster/dagster.yaml` | New: Postgres storage, run coordinator |
| `infras/dagster/workspace.yaml` | New: loads `retail_pulse.orchestration.definitions` |
| `Makefile` | Add `dagster-up`, `dagster-down`, `dagster-logs` |
| `src/retail_pulse/orchestration/dlt_assets.py` | Retry on failure |
| `src/retail_pulse/orchestration/freshness.py` | New: freshness multi-asset check |
| `src/retail_pulse/orchestration/alerts.py` | New: Slack failure sensor |
| `src/retail_pulse/orchestration/definitions.py` | Register the check and the sensor |
| `dbt/models/staging/___sources.yml` | Freshness on the four incremental tables |
| `.env.example` | `SLACK_WEBHOOK_URL`, `DAGSTER_BASE_URL` |
| `pyproject.toml`, `uv.lock` | Add `dagster-postgres` (Postgres run storage) |
| `tests/test_operations.py` | New: tests below |
| `docs/runbook.md` | New |
| `docs/phases/10-operations.md`, `docs/README.md` | New phase guide and its row |
| `docs/Project-Spec.md` | §11 (TBD filled), §14 phase 10, §15, §17 three rows |

## Risks and rollback

- **RAW history.** Nothing here writes to RAW differently. A retry reruns the same dlt pipeline; dlt
  keeps its incremental state, and staging already dedups cursor-boundary rows. No step needs `make seed`,
  `clean-raw` or a full refresh.
- **Two schedulers.** If `make dagster` (dev) runs while the Docker daemon runs, both fire the 23:00
  schedule. The phase guide says to stop one; the runbook covers duplicate runs.
- **Noisy freshness on `product` and `employee`.** They only change when the simulator runs, so they
  will warn on days it does not. That is a warning, not a failure; the runbook says so.
- **Rollback.** `make dagster-down` and revert the PR. Postgres OLTP data and RAW are untouched; the
  `dagster` database can be dropped.

## Test strategy

| Acceptance criterion | Proved by |
| --- | --- |
| AC1, AC3 | Manual: `make dagster-up`, close the terminal, open `localhost:3000`; schedule shows Running and next tick 23:00 |
| AC2 | Manual: run a job, `docker compose restart`, run still listed |
| AC4 | pytest: the dlt asset body raises `RetryRequested` with 2 retries and 300 s when the pipeline fails |
| AC5 | pytest: the dbt op has no retry policy and the job has no op retry policy |
| AC6 | pytest: a `sources.json` fixture with a stale table gives a failed, non-blocking WARN check; a fresh one passes |
| AC7 | pytest: the sensor's message builder includes job, step, first error line and link; the webhook call is mocked |
| AC8 | pytest: with no `SLACK_WEBHOOK_URL`, no HTTP call is made and a log line is written |
| AC9 | Review: the runbook section exists with the three parts |
| R9 | pytest: `.dockerignore` lists `.env`, `.dlt/secrets.toml`, `.snowflake`, `*.p8`; manual `docker compose config` check |

## Changes during the build

- `dagster-postgres` is a new dependency; Postgres run storage needs it.
- `dagster.yaml` sets `scheme: postgresql+psycopg2`: SQLAlchemy 2.1 picks psycopg 3 for `postgresql://`,
  which dagster-postgres does not support.
- `.snowflake/` is mounted at its host path (`REPO_DIR` from the Makefile), so the absolute key paths in
  `.env` and `.dlt/secrets.toml` work unchanged in the containers.
- The daemon keeps dlt's local state in a `dlt_state` volume.
- `uv` is installed in the image with `pip`, not copied from `ghcr.io`.

## Docs to update

Project-Spec §11, §14, §15, §17; `docs/phases/10-operations.md`; `docs/README.md` phase table;
`docs/runbook.md`; `make help`; `.env.example`.
