# Phase 13: Store headcount snapshot (dbt, MetricFlow)

Goal: for every store and every month there is one row with its staffing and sales, so headcount and
revenue per employee can be charted over time and agree with the employee history and the sales fact.
Spec: [004-store-headcount-snapshot](../../specs/004-store-headcount-snapshot/spec.md), Project-Spec
[§10.6](../Project-Spec.md#106-store-headcount-snapshot).

## Why it is needed

Until this phase every fact was a transaction fact: one row per thing that happened (a sale line). A
question about a *state* ("how many people worked at store 5 at the end of March?") had no table. It had to be
rebuilt by hand from `dim_employee` each time: who had started, who had not left yet, and which store
they were at on that day. Doing that by hand is slow and easy to get wrong, because a person who was
transferred has two versions. Revenue per employee also needs that headcount next to the month's sales.
A periodic snapshot computes the state once per store and month, the same way every night.

## Concepts

| Term | Meaning here |
|---|---|
| Periodic snapshot fact | A fact whose rows are the state of something at regular intervals, not events. Here: one row per store per month, also for months where nothing happened. |
| Grain | What one row stands for. `fct_store_headcount_monthly`: one store × one calendar month (local time). |
| Opening / closing headcount | Employees employed at the store at the end of the day before the month starts / at the end of the month's last day. Opening of a month = closing of the previous month. |
| Movements | Joiners (start date in the month), leavers (last working day in the month), transfers in and out (store changes in the employee history). Closing = opening + joiners + transfers in − leavers − transfers out. |
| Semi-additive measure | A measure that can be summed along some dimensions but not others. Headcount sums across stores (10 + 8 people), never across months: 3 months of 10 people is still 10 people, not 30. |
| Employee-month | One employee employed for one month. Average headcount ((opening + closing) / 2) summed over store-months gives employee-months, the denominator of revenue per employee. |
| `non_additive_dimension` | The MetricFlow setting that makes a measure semi-additive: over several months it keeps only the last (or first) month, then sums. |

## What was built

```text
int_employee_scd2 ──▶ int_employee_daily_store ──┐   (state at the end of each local day)
                                                 ├──▶ fct_store_headcount_monthly ──▶ semantic/headcount.yml ──▶ Preset
fct_sales + dim_store + dim_date ────────────────┘   (store × month)                   (metrics)                  (2nd dataset)
```

| File | Does |
|---|---|
| `dbt/models/intermediate/int_employee_daily_store.sql` | One row per employee per local day since 2019-12-31: employed or not at the end of the day, the store, and the day before's values |
| `dbt/models/marts/fct_store_headcount_monthly.sql` | The snapshot: store × month spine, opening and closing headcount, movements, net revenue, `is_month_closed`, `as_of_date` |
| `dbt/macros/headcount_as_of.sql` | "Today" in local time, or the var `headcount_as_of` in unit tests |
| `dbt/models/*/___models.yml` | Column docs, generic tests and the two unit tests (the worked example below) |
| `dbt/tests/assert_headcount_*.sql` | Completeness, opening = previous closing, closing recomputed from history, revenue = `fct_sales` |
| `dbt/models/semantic/headcount.yml` | Semantic model `store_headcount` and its 7 metrics |
| `src/retail_pulse/semantic/preset_export.py` | `make preset-zip` writes a second dataset; semi-additive metrics get a warning text |

## How it works

**1. The state at the end of each day.** For every employee and every local day,
`int_employee_daily_store` answers two questions:

- *Employed at the end of the day?* `start_date <= day` and (`end_date` is null or `end_date > day`). The
  last working day is not employed at its end: that is the day the person leaves.
- *At which store?* The `int_employee_scd2` version whose `[valid_from, valid_to)` contains the instant the
  day ends, local midnight in `Asia/Ho_Chi_Minh`. A transfer at 23:30 local counts that day; one at 00:30
  the next day counts the next day, even though both are the same UTC date.

The table also holds the previous day's two values, so each row says what changed overnight. The seed
makes 80 employees (8 per store), so it is about 80 × 2,480 days, roughly 200,000 rows, rebuilt in full
every night.

**2. Movements are day-to-day changes.** The snapshot never counts start dates, end dates and transfers
separately. It compares each day with the day before:

| Yesterday | Today | Counts as |
| --- | --- | --- |
| not employed | employed at S | joiner at S |
| employed at S | not employed | leaver at S |
| employed at A | employed at B (A ≠ B) | transfer out at A, transfer in at B |

Each month's movements are a sum of these daily differences, so closing = opening + movements always holds.
That includes the awkward cases: a transfer of someone who already left counts nowhere, and a join and a
transfer on the same day count as one joiner at the end-of-day store.

**3. The month row.** `fct_store_headcount_monthly` takes every store in `dim_store` (without `-2`) ×
every month from 2020-01 to the current month. Opening is the count on the day before the month starts.
Closing is the count on the month's last day, or on `as_of_date` for the current month. Movements are
the counts above. Net revenue is the sum of `fct_sales.net_amount` by store and local month. A store-month
with nothing in it gets zeros.

**4. Worked example** (the mart's unit test, `headcount_snapshot_counts_movements_by_store_and_month`). As
of 2020-02-15, with three employees:

- Employee 1 is at store 1 and moves to store 2 on 2020-02-10.
- Employee 3 is at store 1 and leaves on 2020-01-20.
- Employee 2 joins store 2 on 2020-01-05.

| Store | Month | Opening | + Joiners | + In | − Leavers | − Out | = Closing | Average | Net revenue |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2020-01 | 2 (1, 3) | 0 | 0 | 1 (3) | 0 | 1 (1) | 1.5 | 100 |
| 2 | 2020-01 | 0 | 1 (2) | 0 | 0 | 0 | 1 (2) | 0.5 | 0 |
| 1 | 2020-02 | 1 | 0 | 0 | 0 | 1 (1) | 0 | 0.5 | 0 |
| 2 | 2020-02 | 1 | 0 | 1 (1) | 0 | 0 | 2 (1, 2) | 1.5 | 50 |

February is not closed: its closing is as of 2020-02-15. Store 3, with no staff and no sales, still has
two rows of zeros. Revenue per employee for store 2 in February is 50 / 1.5 = 33.3. For store 2 over both
months it is (0 + 50) / (0.5 + 1.5) = 25 per employee per month: a ratio of the sums, not the average of
the two monthly ratios. Headcount for store 2 over both months is 2, the closing of February, not 1 + 2.

**5. The metrics.** `dbt/models/semantic/headcount.yml`:

| Metric | Formula |
| --- | --- |
| `closing_headcount` | `SUM(closing_headcount)` across stores, last month only over time (`non_additive_dimension`, `window_choice: max`) |
| `opening_headcount` | same, first month only (`window_choice: min`) |
| `employee_months` | `SUM(average_headcount)` |
| `store_net_revenue` | `SUM(net_revenue)` |
| `joiners`, `leavers` | `SUM(...)` |
| `revenue_per_employee` | `store_net_revenue / employee_months`, a ratio; MetricFlow adds `NULLIF`, so no staff gives an empty value |

What MetricFlow generates for headcount by quarter (`mf query --explain`). The join keeps only each
quarter's last month:

```sql
SELECT subq_2.metric_time__quarter, subq_2.store_month__store_name,
       SUM(subq_2.__closing_headcount) AS closing_headcount
FROM (... fct_store_headcount_monthly ...) subq_2
INNER JOIN (
  SELECT DATE_TRUNC('quarter', month_start) AS metric_time__quarter,
         MAX(DATE_TRUNC('month', month_start)) AS month_start__month__complete
  FROM RETAIL_PULSE.marts.fct_store_headcount_monthly
  GROUP BY DATE_TRUNC('quarter', month_start)
) subq_4 ON subq_2.month_start__month = subq_4.month_start__month__complete
GROUP BY ...
```

**6. Preset.** A Preset metric is one SQL expression on one dataset, so it cannot hold that join. `make
preset-zip` therefore writes `closing_headcount` and `opening_headcount` as `SUM(...)` with a warning
text, shown next to the metric: "Semi-additive: sums across stores only. Always group by month; never
total over several months." Every other metric, including `revenue_per_employee`, is exact as one
expression. A multi-month headcount comes from `mf query`, not from Preset.

## Decisions

Decision log entries: [Project-Spec §17](../Project-Spec.md#17-decision-log) (spec 004 rows).

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| How movements are counted | Day-to-day changes of an end-of-day state table | Counting start dates, end dates and history versions separately | Separate counts break closing = opening + movements whenever a transfer falls on a join or leave day |
| Last working day | Leaver of that month, not in its closing | Still counted on the last day | Keeps the identity exact; "employed after the day" is one rule for every day |
| Store before the first transfer | First known store (version from 1900-01-01) | Unknown store | Transfers are only recorded since the simulator started; the first store is the best fact there is |
| Revenue per employee | Metric `SUM(net_revenue) / SUM(average_headcount)` | A column on the mart; `AVG` of monthly ratios | One definition (§17, ratios of sums); a column would be a second definition |
| Current month | A row with `is_month_closed = false`, values as of `as_of_date` | Leave it out until closed | Owner's choice (Q2): see this month early, with a flag |
| Headcount in Preset | Plain `SUM` with a warning text | Leave the metric out of Preset | Charts by month are correct and common; the warning covers the rest |

## Run and verify

```bash
make dbt-parse                                   # the new models parse
make dbt-build                                   # dev: builds the two models into DBT_<NAME>_*, runs their tests
cd dbt && uv run mf query --metrics closing_headcount,revenue_per_employee \
  --group-by metric_time__quarter,store_month__store_name --explain   # SQL keeps the last month
```

The dbt tests prove the contract on every build: one row per store and month, opening = previous
closing, the identity, closing recomputed straight from the history, revenue equal to `fct_sales`, and
exactly the current month not closed.

Recompute one store-month yourself in Snowsight (here store 1, March 2024, as of the month's last day):

```sql
-- 1. The snapshot row
SELECT * FROM RETAIL_PULSE.MARTS.FCT_STORE_HEADCOUNT_MONTHLY
WHERE store_id = 1 AND month_start = '2024-03-01';

-- 2. Who was employed at store 1 at the end of 2024-03-31, straight from the history
SELECT employee_id, employee_name, start_date, end_date, valid_from, valid_to
FROM RETAIL_PULSE.INTERMEDIATE.INT_EMPLOYEE_SCD2
WHERE store_id = 1
  AND start_date <= '2024-03-31' AND (end_date IS NULL OR end_date > '2024-03-31')
  AND valid_from <= TIMESTAMP_TZ_FROM_PARTS(2024, 4, 1, 0, 0, 0, 0, 'Asia/Ho_Chi_Minh')
  AND valid_to   >  TIMESTAMP_TZ_FROM_PARTS(2024, 4, 1, 0, 0, 0, 0, 'Asia/Ho_Chi_Minh');
-- the row count is closing_headcount; repeat with 2024-02-29 for opening_headcount

-- 3. Joiners and leavers at store 1 in March
SELECT employee_id, start_date, end_date FROM RETAIL_PULSE.INTERMEDIATE.INT_EMPLOYEE_SCD2
WHERE store_id = 1 AND is_current
  AND (start_date BETWEEN '2024-03-01' AND '2024-03-31' OR end_date BETWEEN '2024-03-01' AND '2024-03-31');
```

The third query uses the current store. For an employee who was transferred, check their versions: a
leaver counts at the store they were at on their last day.

After `make stream` moves an employee and the next 23:00 run has built, their old store shows one
`transfers_out` and the new one one `transfers_in` in the current month.

In Preset, import the new ZIP ([phase 11](11-semantic-layer.md), step 3) and build the chart **Revenue
per employee by store and month**: dataset `FCT_STORE_HEADCOUNT_MONTHLY`, time `MONTH_START` at month
grain, dimension `STORE_NAME`, saved metric `revenue_per_employee`. One cell must equal
`net_revenue / average_headcount` of that row.

## Errors encountered

| Symptom | Cause | Fix |
|---|---|---|
| A unit test that depends on "today" would change result every day | The snapshot runs up to the current day | The macro `headcount_as_of()` reads the var `headcount_as_of`; unit tests set it |
| A build at 23:00 could pass midnight between the two models | "Today" read twice gives two different days | The mart takes its as-of day from the daily table's last day, not from the clock |

## Further reading

- [Kimball: periodic snapshot fact tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/periodic-snapshot-fact-table/)
- [Kimball: additive, semi-additive and non-additive facts](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/additive-semi-additive-non-additive-fact/)
- [dbt: semi-additive measures](https://docs.getdbt.com/docs/build/measures#non-additive-dimensions)
- [dbt: unit tests](https://docs.getdbt.com/docs/build/unit-tests)
- [Snowflake: TIMESTAMP_TZ_FROM_PARTS](https://docs.snowflake.com/en/sql-reference/functions/timestamp_from_parts)
