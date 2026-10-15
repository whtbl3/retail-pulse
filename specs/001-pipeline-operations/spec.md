# 001: Pipeline operations

- Status: Approved (2026-10-15, PhucLH)
- Intent: none (roadmap step 5)
- Project-Spec sections affected: §11, §15, §17

## Problem

The pipeline only runs while someone keeps `make dagster` open in a terminal, and run history is lost
when it closes. When the nightly run fails, nobody finds out until they open the Dagster UI. Stale RAW
data is not detected: a `freshness` rule exists on `raw.sales_transaction`, but nothing evaluates it.
When something breaks, there is no written procedure for what to do. Spec §11 lists retry policy,
sensors, alerting and deployment topology as TBD.

## Goal

The daily pipeline runs on its own, survives restarts with its history intact, retries what is safe to
retry, warns when RAW stops getting new data, tells the owner when a run fails, and every failure type
has a written response.

## Scope

In scope:

- Running Dagster continuously on the local machine through Docker Compose.
- Retry policy for the scheduled pipeline.
- Freshness of the incremental RAW tables.
- A notification when a run fails.
- A runbook for the failure types this pipeline can have.

Out of scope:

- Cloud deployment, Kubernetes or Dagster+ (spec §17: Docker Compose only).
- Scheduling the product simulator (`stream.py`).
- Changing what the pipeline computes: dlt load strategies, dbt models and Great Expectations checks
  stay as they are.
- CDC (a separate feature).

## Requirements

1. **R1:** One command starts the Dagster UI and the scheduler in the background; they keep running
   after the terminal closes and come back after a machine restart once Docker is started.
2. **R2:** Run history, schedules and asset metadata survive a restart of the Dagster containers.
3. **R3:** The daily schedule fires at 23:00 `Asia/Ho_Chi_Minh` without anyone having the UI open.
4. **R4:** A failed ingestion step is retried automatically before the run is marked failed. dbt
   steps and Great Expectations checks are not retried, because a retry would not change their result.
5. **R5:** Each incremental RAW table (`sales_transaction`, `sales_transaction_item`, `product`,
   `employee`) has a freshness rule. A stale table shows as a warning in Dagster and does not stop the run.
6. **R6:** When a run of `full_pipeline` or `fct_sales_full_refresh` fails, a message reaches the
   owner with the job name, the failed step, the error's first line and a link to the run.
7. **R7:** If no notification channel is configured, the pipeline still runs and the failure is
   logged; a missing channel never fails a run.
8. **R8:** A runbook lists each failure type, how to recognise it and the steps to recover, and
   names any recovery step that must never be taken (for example deleting RAW).
9. **R9:** No secret (Snowflake key, webhook URL) is stored in the repo or baked into an image.

## Acceptance criteria

- **AC1:** Given Docker is running, when the owner runs the start command and closes the terminal,
  then the Dagster UI still answers at `http://localhost:3000`.
- **AC2:** Given a completed run, when the Dagster containers are restarted, then that run is still
  listed in the UI.
- **AC3:** Given the containers are running and the schedule is on, when the clock reaches 23:00
  `Asia/Ho_Chi_Minh`, then a `full_pipeline` run starts with no one logged in to the UI.
- **AC4:** Given the ingestion step fails once with a transient error, when the run continues, then
  the step is retried and the run succeeds if the retry succeeds.
- **AC5:** Given a dbt test fails, when the run ends, then the dbt step was attempted once.
- **AC6:** Given `raw.sales_transaction` has no row newer than the freshness limit, when freshness is
  checked, then Dagster shows a warning for that table and the run is not stopped by it.
- **AC7:** Given a notification channel is configured, when `full_pipeline` fails, then one message
  arrives with the job name, failed step, first error line and run link.
- **AC8:** Given no notification channel is configured, when a run fails, then the run's own status is
  unchanged by the missing channel and a log line says no notification was sent.
- **AC9:** Given the runbook, when the owner looks up "Great Expectations check failed", then it says
  how to find the failing rows, what usually causes it, and how to rerun once fixed.

## Data contract changes

None to tables or columns. Freshness rules are added to the dbt source definitions of the four
incremental RAW tables.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Dagster runs as Docker Compose services next to Postgres, with its run storage in Postgres | Accepted | Docker Compose is the only deployment target (§17); Postgres storage keeps history across restarts |
| Only ingestion is retried | Accepted | dbt and data-quality failures are deterministic; retrying them hides the error and costs warehouse time |
| Stale RAW warns, never blocks | Accepted | A quiet day is not an error; blocking would stop dbt from building what did arrive |

## Answers to open questions

- **Q1 Notification channel:** Slack, through an incoming webhook.
- **Q2 Freshness limit:** warn after 26 hours without new rows, error after 3 days. Both are warnings
  in Dagster; neither stops the run (R5).
- **Q3 Retries:** ingestion is retried 2 times, 5 minutes apart.
- **Q4 Dev mode:** `make dagster` stays for development; the Docker setup is for scheduled runs.
