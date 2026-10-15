# 002: Log-based CDC from PostgreSQL

- Status: Draft
- Intent: none (roadmap step 6)
- Project-Spec sections affected: §5, §8.2, §9.2, §10.4, §11, §14, §15, §17

## Problem

Ingestion reads each table with a query on `updated_at`, so it only sees a row's state at the moment
the pipeline runs. If `stream.py` changes the same product twice between two nightly runs, the first
version never reaches RAW and the SCD2 history in `dim_product` and `dim_employee` silently misses it
(§9.2, known limitations). A query cursor also cannot see deleted rows. The decision "Incremental
ingestion before CDC" (§17) deferred this until the incremental path worked end to end; it now does.

## Goal

Every committed change to the captured tables reaches RAW in commit order, including versions that
were overwritten before the next pipeline run, and SCD2 dimensions are built from all of them. The
existing marts give the same results on data that changed at most once between runs.

## Scope

In scope:

- Capturing inserts and updates (and deletes, see open question 2) from PostgreSQL's change log for
  the captured tables.
- Landing those changes append-only in Snowflake RAW, with the order and type of each change.
- Building staging and the SCD2 dimensions from the captured changes, keeping the RAW history that
  exists today.
- Running capture as part of the existing `full_pipeline` and surfacing capture problems in Dagster
  and Slack like other failures.

Out of scope:

- Streaming or near-real-time delivery to Snowflake; loads stay batch.
- Changing what the marts compute, their grain or their keys.
- Return and cancellation analysis, even if deletes or status changes are captured (§6.2).
- Schema changes on the source tables (DDL replication).
- Any change that deletes or replaces existing RAW rows of `product` or `employee`.

## Requirements

1. **R1:** For each captured table, every committed insert and update since the previous load lands
   in RAW, including several updates to the same row between two loads, each as its own RAW row.
2. **R2:** Each captured RAW row carries its operation type and a value that orders changes in commit
   order, so staging can tell which version came first even when `updated_at` is equal.
3. **R3:** Captured changes are never lost because the pipeline did not run: changes made while
   ingestion is down or failed are delivered on the next successful run.
4. **R4:** A rerun after a failed or retried load does not create duplicate versions in staging or
   the dimensions.
5. **R5:** The switch-over keeps every RAW row that exists today. Versions loaded before CDC and
   versions captured after it form one continuous history per key, with no gap and no duplicate at
   the boundary.
6. **R6:** On the same source data, `fct_sales` and every dimension give the same rows and measures
   before and after the switch, except for the versions the old path could not see.
7. **R7:** The amount of change data retained by PostgreSQL for capture is visible in Dagster, and a
   warning is raised before it can fill the source disk. The warning does not stop the run.
8. **R8:** Capture runs inside `full_pipeline` at its current schedule; dbt does not run if capture
   fails, and capture failures are retried and alerted like the current ingestion.
9. **R9:** The runbook covers capture-specific failures and states how to recover without deleting
   RAW.

## Acceptance criteria

- **AC1:** Given a product whose `unit_cost` changes twice between two pipeline runs, when the next
  run completes, then RAW holds both changes and `dim_product` has a version for each.
- **AC2:** Given an employee transferred A → B → A between two runs, when the next run completes,
  then `dim_employee` has three versions for that employee.
- **AC3:** Given changes made while Dagster is stopped, when it starts and `full_pipeline` runs, then
  all of those changes are in RAW.
- **AC4:** Given a capture load that fails after writing part of its batch and is retried, when the
  run succeeds, then staging has no duplicate version for any key.
- **AC5:** Given the RAW history that exists before the switch, when the first CDC run completes,
  then no pre-existing RAW row was deleted and each key's version history has no gap or duplicate at
  the switch-over point.
- **AC6:** Given source data where no row changed more than once between runs, when the old and new
  paths are both built, then `fct_sales` and every dimension match row for row.
- **AC7:** Given retained change data above the warning limit, when the pipeline runs, then Dagster
  shows a warning for it and the run is not stopped by it.
- **AC8:** Given capture fails on every retry, when the run ends, then dbt did not run and one Slack
  failure message names the capture step.
- **AC9:** Given the runbook, when the owner looks up "capture is behind" or "capture state lost",
  then it says how to recognise it and how to recover without deleting RAW.

## Data contract changes

- The captured tables in RAW gain an operation type column and a change-order column (R2). Whether
  they are new RAW tables or columns on the existing ones is open question 5.
- Staging for the captured tables deduplicates on the change order instead of only `updated_at`.
- Load strategy in §9.2 changes from "Incremental append on `updated_at`" to "Log-based CDC, append"
  for the captured tables. Small reference tables keep Replace unless open question 1 says otherwise.
- Marts: no change to columns, grain or keys.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| "Incremental ingestion before CDC" (Final) is fulfilled and superseded: the captured tables move to log-based CDC | Proposed | The incremental path is delivered end to end; its known limitations (lost intermediate versions, no deletes) are what CDC removes |
| §9.2 "Log-based CDC is out of scope" is removed | Proposed | This spec brings it into scope |
| CDC loads stay batch, inside `full_pipeline` | Proposed | Keeps one schedule, one place for retries and alerts, and Snowflake compute low |
| RAW stays append-only and keeps all pre-CDC rows | Proposed | RAW is the only history store (Final) |

## Open questions

1. [NEEDS CLARIFICATION] Which tables are captured: the four incremental tables
   (`sales_transaction`, `sales_transaction_item`, `product`, `employee`), only `product` and
   `employee`, or all ten? Recommended: the four incremental tables.
2. [NEEDS CLARIFICATION] Are deletes captured? The source never deletes today. Recommended: capture
   them into RAW with their operation type, with no change to marts.
3. [NEEDS CLARIFICATION] How often is the change log read: once a night inside `full_pipeline`, or
   more often (for example hourly) into RAW with dbt still nightly? Recommended: nightly only.
4. [NEEDS CLARIFICATION] Does CDC replace the `updated_at` cursor for the captured tables, or run
   alongside it for a while? Recommended: replace it.
5. [NEEDS CLARIFICATION] Where do captured changes land: new RAW tables that staging unions with the
   existing ones, or the existing RAW tables with new columns? Recommended: new RAW tables, so the
   existing tables are never altered.
6. [NEEDS CLARIFICATION] Warning limit for retained change data (R7). Recommended: warn at 1 GB.
