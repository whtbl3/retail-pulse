# 006: Warehouse cost and run time monitoring

- Status: Draft
- Intent: none (requested by the project owner, 2026-10-15, as a next step towards a senior-level
  portfolio)
- Project-Spec sections affected: §10.2 (new marts), §11 (new check), §12 (new chart), §13.4, §14
  (new phase), §17

## Problem

The pipeline warns when it fails or when RAW is stale, but not when it costs more or runs longer than
usual. Snowflake credits are only capped by the monthly resource monitors (10 credits for the pipeline
warehouse, 2 for CI), which notify at 80 percent of the month's cap and suspend the warehouse at 100: a
slow model, a mistaken full refresh or a bigger warehouse shows up only as the month's total, late, and
without saying which day or model caused it. Nobody can answer "how much does
a night cost, and which model takes the longest" without logging in to Snowsight.

## Goal

Every day the warehouse shows how many credits each warehouse used and how long the pipeline and each
model took. When a day costs or takes clearly more than usual, the owner gets one Slack message the
same night, early enough to act before the monthly cap suspends the warehouse.

## Scope

In scope:

- Daily credits for the pipeline warehouse and the CI warehouse (Q1).
- Run time of each scheduled pipeline run and of each dbt model in it.
- A warning on Slack, through the existing alert channel, when cost or run time crosses a threshold
  set relative to recent days (Q2).
- One Preset chart of daily credits (Q3).
- A phase guide explaining where the numbers come from, their delay, and what to do on a warning.

Out of scope:

- Changing warehouse sizes, resource monitor caps or schedules.
- Cost per query, per user or per Preset dashboard.
- Storage cost.
- Any change to RAW, SCD2 history or existing marts.
- Infrastructure as code for Snowflake.

## Requirements

1. **R1:** A mart holds one row per warehouse per day with the credits used that day, from the day
   monitoring starts reading data (or earlier if Snowflake still keeps it).
2. **R2:** A mart holds, for each scheduled pipeline run, its start, end and duration, and for each
   dbt model in it, its duration.
3. **R3:** Credits in the mart match the credits Snowflake reports for the same warehouse and day.
4. **R4:** After each scheduled run, the pipeline compares the last complete day's credits per
   warehouse and the run's duration with twice the median of the last 14 complete days (or runs),
   never below a fixed floor (Q2), and sends one Slack message when either is crossed, naming the
   figure, the threshold and the slowest models.
5. **R5:** A cost or run-time warning never fails or blocks the pipeline, the same as the RAW
   freshness warning.
6. **R6:** Days whose figures are not final yet, because Snowflake reports usage with a delay, are
   marked as such and never trigger a warning.
7. **R7:** The pipeline and CI keep working when the account-usage data cannot be read (for example in
   CI, whose role has no access): the cost models and checks are skipped or empty with a clear message,
   not a failure of unrelated models.
8. **R8:** The only new privilege is read access to Snowflake's usage data for the transformation
   role, granted once by the owner with a statement given in the docs.
9. **R9:** The phase guide explains the sources of the figures, their delay, the thresholds and what to
   check on a warning.

## Acceptance criteria

- **AC1:** Given the access granted, when the pipeline has run, then the cost mart has one row per
  warehouse in scope per day, and a day's credits equal Snowsight's figure for that warehouse and day.
- **AC2:** Given a scheduled run, when it finishes, then the run-time mart has its duration and the
  duration of each model built in it.
- **AC3:** Given a day whose credits cross the threshold, when the next scheduled run finishes, then
  exactly one Slack message names the warehouse, the credits and the threshold.
- **AC4:** Given a run whose duration crosses the threshold, when it finishes, then one Slack message
  names the duration, the threshold and the slowest models.
- **AC5:** Given a warning, when it is sent, then the run's status is unchanged and dbt has built
  everything else.
- **AC6:** Given today's not-yet-final usage, when the check runs, then it does not warn on it.
- **AC7:** Given a pull request touching dbt, when CI runs without account-usage access, then CI
  passes.
- **AC8:** Given the Preset chart, when it shows a day, then its credits match the mart.
- **AC9:** Given the phase guide, when a reader gets a warning, then they can find which model or
  warehouse caused it with the steps given.

## Data contract changes

Two new marts (daily credits per warehouse; run and model durations). No existing table, column,
grain or load strategy changes.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Cost and run-time warnings never block the pipeline | Proposed | Same as RAW freshness: a costly night is not wrong data |
| Only complete days are compared with the threshold | Proposed | Snowflake reports usage with a delay; a partial day would look cheap or trigger false alarms |
| Monitoring needs only read access to Snowflake's usage data, granted by the owner | Proposed | Least privilege (§13.4); no role gains rights to change warehouses |

## Answers to open questions

Answered by the owner on 2026-10-15 (decision cards in the project thread).

- **Q1, warehouses:** both, the pipeline warehouse and the CI warehouse, one row each per day.
- **Q2, threshold:** relative. Warn above twice the median of the last 14 complete days, with a small
  fixed floor so near-zero days do not alert.
- **Q3, reach:** marts, Slack warning and one Preset chart of daily credits.

## Open questions

None.
