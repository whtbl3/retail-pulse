# 004: Monthly store headcount snapshot, plan

Spec: [spec.md](spec.md)

## Approach

Layers touched: dbt (one intermediate model, one mart, tests), the semantic layer, the Preset export
script, docs. Postgres, the generators, dlt, Snowflake RAW, Great Expectations and the Dagster job
definitions are not touched; Dagster picks up the new models from the dbt manifest.

1. **Daily employee state, then monthly sums (R2 to R5).** A new table
   `int_employee_daily_store` holds one row per employee per local calendar day, from 2019-12-31 (the
   day before the first covered month) to the build day, with the employee's state *at the end of that
   day*: employed or not (employed when `start_date <= day` and `end_date` is null or `> day`, so the
   last working day is not employed at its end, R2) and the store from `int_employee_scd2`, the version
   whose `[valid_from, valid_to)` contains the instant the day ends (local midnight, `Asia/Ho_Chi_Minh`,
   as in `fct_sales`). The first version is valid from 1900, so days before the first transfer take the
   first known store (decision 2 of the spec). Size: about 80 employees x 2,500 days, roughly 200,000
   rows, trivial for Snowflake and rebuilt in full every run.

   Comparing each day with the day before gives every movement, with nothing else to reconcile:

   | Yesterday | Today | Counts as |
   | --- | --- | --- |
   | not employed | employed at S | joiner at S |
   | employed at S | not employed | leaver at S |
   | employed at A | employed at B, A != B | transfer out at A, transfer in at B |

   Closing headcount of a month is the count of employed rows on its last day (on the build day for the
   current month); opening is the count on the day before the month starts. Because the monthly flows
   are sums of day-to-day differences, R5's identity and "opening = previous closing" hold by
   construction, also for the edge cases: a transfer of someone not employed counts nowhere, a join and
   a transfer on the same day is one joiner at the end-of-day store, and several transfers in one day
   collapse to the end-of-day store. This "end of day" reading of "the store on their start date" (R3)
   is written in the model docs and the phase guide.

   Why not count events straight from the history: start date, end date and store changes come from
   different columns and clocks (dates vs timestamps), and counting them separately breaks the identity
   whenever a transfer touches a join or leave day. The daily table removes that class of bug and is
   the worked example in the guide.

2. **The mart `fct_store_headcount_monthly` (R1, R6, R9, R10).** Spine: every store in `dim_store`
   (without the `-2` member) x every month from January 2020 to the build month (local date), so empty
   store-months exist with zeros (R1). Columns: `store_key`, `store_id`, `store_name`, `month_start`
   (date), `month_start_date_key` (to `dim_date`), `opening_headcount`, `closing_headcount`, `joiners`,
   `leavers`, `transfers_in`, `transfers_out`, `average_headcount` ((opening + closing) / 2, Q1),
   `net_revenue` and `is_month_closed` (false only for the build month, Q2). `store_name` and
   `month_start` are on the fact for the same reason as `fct_sales_enriched`: Preset and the semantic
   layer read one table without joins. Net revenue sums `fct_sales.net_amount` by `store_key` and the
   month of `date_key` (local), completed sales only as in `fct_sales` (R6). Materialized as a table,
   rebuilt in full every run: deterministic for the same data on the same day (R9). Revenue per employee
   is not a column; it is defined once, in the semantic layer (R8).

3. **Semantic layer (R7, R8, R11).** A second semantic model `store_headcount` on the mart in a new
   `dbt/models/semantic/headcount.yml`, time dimension `month_start` at month grain, dimension
   `store_name`. Measures: `closing_headcount` and `opening_headcount` are `sum` with
   `non_additive_dimension: month_start` (`window_choice: max` for closing, `min` for opening), so
   MetricFlow sums across stores but takes the last (first) month over time; `headcount_months` sums
   `average_headcount`; `store_month_net_revenue` sums `net_revenue`. Metrics: `closing_headcount`,
   `opening_headcount`, `employee_months`, `store_net_revenue` and `revenue_per_employee`, a `ratio` of
   `store_net_revenue` to `employee_months`. MetricFlow renders a ratio with `NULLIF` on the
   denominator (seen in `tests/test_preset_export.py`), so zero headcount gives an empty value (AC6).
   Over several months it is revenue divided by employee-months, which is what AC9 asks; the
   description says "per employee per month". `non_additive_dimension` and `window_choice` were
   checked in the installed `metricflow_semantic_interfaces` source.

4. **Preset (R11).** `make preset-zip` today writes one dataset (`fct_sales_enriched`) and turns every
   metric into one SQL expression. It changes to write one dataset per semantic model, with the same
   database and template from the owner's export, a fixed uuid per model, and each metric on the
   dataset of its semantic model. Revenue per employee becomes one expression
   (`CAST(SUM(net_revenue) ...) / CAST(NULLIF(SUM(average_headcount), 0) ...)`). A semi-additive
   metric cannot: MetricFlow's SQL for it has a subquery with a filter on the last month, which
   `to_expression` rejects and Superset cannot store as one expression. For those, the export writes
   the plain `SUM(closing_headcount)` and fills Superset's `warning_text` ("Sum across stores only.
   Always group by month; never total over several months."), which Preset shows next to the metric
   (R7). The chart (revenue per employee, store x month) is built by hand in Preset from the imported
   dataset, as in phase 7, and added to the dashboard.

5. **Docs (R12).** `docs/phases/13-headcount-snapshot.md` from `docs/phases/_template.md`: why a
   periodic snapshot, the terms (periodic snapshot, grain, semi-additive, opening and closing
   headcount, employee-month), the daily-state table above, and a worked example on real rows: pick one
   store-month in Snowsight, list its employees from `int_employee_scd2`, recompute closing, joiners,
   leavers and transfers by hand, compare with the mart. Plus Project-Spec and design doc updates below.

## Files

| File | Change |
| --- | --- |
| `dbt/models/intermediate/int_employee_daily_store.sql` | New: employee x day state at end of day |
| `dbt/models/intermediate/___models.yml` | Docs and tests for it, plus the unit tests (worked cases) |
| `dbt/models/marts/fct_store_headcount_monthly.sql` | New: the snapshot mart |
| `dbt/models/marts/___models.yml` | Columns, `semi-additive` warnings in descriptions, generic tests |
| `dbt/tests/assert_headcount_*.sql` | New singular tests (see Test strategy) |
| `dbt/models/semantic/headcount.yml` | New semantic model and metrics |
| `src/retail_pulse/semantic/preset_export.py` | One dataset per semantic model; semi-additive metrics as plain sum with warning text |
| `tests/test_semantic_layer.py`, `tests/test_preset_export.py` | New metrics, non-additive config, two datasets in the ZIP |
| `Makefile` | `preset-zip` help text (now two datasets) |

## Risks and rollback

- **RAW and SCD2 history are not touched.** Both new models only read `int_employee_scd2` and
  `fct_sales`. No `make seed`, `reseed`, `db-reset`, `clean-raw` and no full refresh of `fct_sales`. The
  first prod build (the 23:00 run after merge) creates two new tables and changes no existing one.
- **Unknown keys in `fct_sales`.** Sales with store or date key `-2` belong to no store-month. If any
  exist, AC4's grand total test fails and says how much revenue is unassigned; the fix is the existing
  `fct_sales` full refresh (phase 5), not a change here.
- **Time zone at day end.** `valid_from`/`valid_to` are timestamps; the day end is local midnight
  converted the same way as in `fct_sales`. A unit test with a transfer at 23:30 local pins it.
- **Current month moves.** The build-month row changes on every run and the next month appears on the
  first run of a month. That is Q2's intent; the flag tells readers.
- **Preset shows a sum for headcount.** Preset cannot hold the last-month rule in one expression; the
  warning text and the guide carry R7 there. The semantic layer (`mf query`) gives the correct value.
- **Preset import of a second dataset.** Same import path as phase 11, new dataset uuid, so the existing
  `fct_sales_enriched` dataset and its charts are not changed.
- **Rollback:** revert the PR. The two tables stay in `MARTS` unused until dropped by hand
  (`DROP TABLE RETAIL_PULSE.MARTS.FCT_STORE_HEADCOUNT_MONTHLY`, same for the intermediate one); the
  Preset dataset is deleted in Preset.

## Test strategy

dbt tests run in slim CI against the PR schemas (the new models are "modified", so CI builds and tests
them on real data). dbt unit tests (dbt 1.8+, installed 1.12.5) fix the edge cases on hand-made rows.
pytest covers the semantic layer and the export offline. Owner checks need the 23:00 run or `mf query`.

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | dbt: `dbt_utils.unique_combination_of_columns` on store and month; singular test rows = stores x months from Jan 2020 to the build month |
| AC2 | dbt singular test: identity holds and `opening = LAG(closing)` for every store-month |
| AC3 | dbt singular test: closing headcount recomputed directly from `int_employee_scd2` (not from the daily table) for every store-month |
| AC4 | dbt singular test: completed net revenue from `fct_sales` by store and local month equals the mart, and grand totals match |
| AC5 | dbt unit test: a transfer A to B mid-month gives one transfer out at A, one in at B, B's closing includes the employee. Owner: after `make stream` and the next build, the same on real rows |
| AC6 | dbt unit test: a store-month with no staff has headcount 0; pytest: the metric SQL has `NULLIF` on the denominator |
| AC7 | Review: column descriptions, metric descriptions, Preset warning text and the phase guide say "never sum over months" and how to get a multi-month figure |
| AC8 | dbt singular test: exactly one month has `is_month_closed = false` and it is the build month; months run from 2020-01 to it |
| AC9 | pytest: `mf query --explain` for `closing_headcount` by quarter selects the last month (window `max` on `month_start`); `revenue_per_employee` is a ratio of the two sums. Owner: `mf query` for one store and quarter against the mart |
| AC10 | pytest: the export's revenue per employee expression; Owner: the Preset chart for one store-month matches the mart |
| AC11 | Review of `docs/phases/13-headcount-snapshot.md`, including the worked example |

Unit test cases for `int_employee_daily_store` and the mart: joiner on the 1st; leaver on the last day
of a month (leaver of that month, not in its closing); transfer at 23:30 local; join and transfer on the
same day; transfer of an employee after their end date (counts nowhere); employee starting before 2020
(in Jan 2020 opening).

## Docs to update

- `docs/Project-Spec.md`: §10.2 (new model row), new §10.6 "Store headcount snapshot" (grain,
  measures, semi-additive rule, end-of-day reading), §12 (new metrics, chart, second dataset), §14
  (phase 13), §17 (the spec's four decisions as Final).
- `docs/design/analytical-data-modeling.md`: the second business process and its fact type.
- `docs/phases/13-headcount-snapshot.md` (new, from `_template.md`) and its row in `docs/README.md`.
- `docs/phases/11-semantic-layer.md` and `07-preset.md`: `make preset-zip` now writes two datasets.
- `make help` text for `preset-zip`.
