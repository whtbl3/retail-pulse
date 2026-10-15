# 006: Warehouse cost and run time monitoring, plan

Spec: [spec.md](spec.md)

## Approach

Layers touched: Snowflake (one read grant, by the owner), dbt (a source, two marts, a macro), the
semantic layer and Preset export, Dagster (one sensor, a few lines in the dbt asset), docs. Postgres,
dlt, RAW and the existing marts are not touched. Built after spec 005, so the two new marts carry
contracts like every other mart.

1. **Read access (R8).** The owner runs once, as ACCOUNTADMIN, a grant that lets `TRANSFORMER` read
   the `SNOWFLAKE.ACCOUNT_USAGE` views `WAREHOUSE_METERING_HISTORY` and `QUERY_HISTORY`. The preferred
   form is a Snowflake database role on the `SNOWFLAKE` database that covers exactly these views;
   `GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE` is the fallback. Which database role covers both
   views is checked in Snowflake's docs during T1, before anything is written, and the statement goes
   into `infras/snowflake/init.sql` (commented, owner-run) and the phase guide. No role gains any
   right to change a warehouse.
2. **Credits per warehouse per day (R1, R3, R6, Q1).** A dbt source `snowflake_account_usage` and a
   mart `fct_warehouse_credits_daily`: one row per warehouse (`RETAIL_WH`, `RETAIL_CI_WH`) per local
   day, `credits_used` summed from the hourly metering rows. `is_complete_day` is true for days before
   today (local); usage views report with a delay, so only complete days are compared. Next to each
   complete day: `median_credits_14d` (median of the previous 14 complete days of that warehouse),
   `credit_threshold = max(2 × median, floor)` with a floor of 0.5 credit, and `is_above_threshold`
   (Q2). The comparison lives in SQL so dbt unit tests prove it.
3. **Run time per model (R2).** dbt-snowflake tags its queries only when a model sets `query_tag`
   (`snowflake__set_query_tag` in the installed adapter). A project macro of the same name sets the
   tag to `retail_pulse|<target>|<model>|<invocation_id>` on every model and test, so `QUERY_HISTORY`
   tells which model and which run each query belongs to. Mart `fct_dbt_model_runs`: one row per
   prod invocation and model with start, end and duration, plus the invocation's total. Query
   history arrives with a delay too, so this mart is for history and the chart, not for tonight's
   alert. That the project macro takes precedence over the adapter's is checked in T4 with
   `dbt compile` output before relying on it.
4. **Tonight's warning (R4, R5, Q2).** A Dagster `run_status_sensor` on `full_pipeline` success,
   next to the existing failure sensor in `alerts.py`:
   - Run time: this run's duration from the Dagster run record, compared with
     `max(2 × median of the last 14 successful full_pipeline runs, 20 minutes)`, both from Dagster's
     run storage (PostgreSQL, phase 10). The slowest models come from this run: the dbt asset reads
     `run_results.json` after `dbt build` (`DbtCliInvocation.get_artifact`, present in the installed
     dagster-dbt) and stores the three slowest models as a run tag.
   - Credits: rows of `fct_warehouse_credits_daily` for the last complete day with
     `is_above_threshold`, read with the same Snowflake key-pair login as dbt.
   - One Slack message per crossed figure through the existing `post_to_slack`; the sensor only posts,
     so a warning never changes the run's status (R5). Without `SLACK_WEBHOOK_URL` it logs one line,
     as the failure alert does.
5. **CI without usage access (R7).** `CI_RUNNER` cannot read `ACCOUNT_USAGE`. The two monitoring marts
   get `+enabled: "{{ target.name != 'ci' }}"`, so slim CI skips them, and the semantic model on them
   is skipped with them. Their SQL is still compiled offline by pytest, and their dbt unit and data
   tests run on every dev build and on the 23:00 prod build (Dagster runs `dbt build`).
6. **Chart (Q3).** A semantic model `warehouse_credits` with the metric `warehouse_credits` (sum of
   `credits_used`) and a third dataset in `make preset-zip`. The owner builds "Daily credits by
   warehouse" (bar, by day and warehouse) and adds it to the dashboard.
7. **Docs (R9).** `docs/phases/14-cost-monitoring.md` from the template: where each figure comes from,
   the delays, the thresholds, the grant, and "what to check on a warning" (slowest models in the
   message, then `fct_dbt_model_runs` for the trend).

## Files

| File | Change |
| --- | --- |
| `infras/snowflake/init.sql` | The read grant, commented, owner-run |
| `dbt/models/staging/___sources.yml` | Source `snowflake_account_usage` (two views) |
| `dbt/macros/snowflake__set_query_tag.sql` | Tag every model's queries with target, model and invocation |
| `dbt/models/marts/fct_warehouse_credits_daily.sql` | Daily credits, completeness, threshold |
| `dbt/models/marts/fct_dbt_model_runs.sql` | Model durations per prod invocation |
| `dbt/models/marts/___models.yml` | Docs, contracts, tests and unit tests of the two marts |
| `dbt/dbt_project.yml` | `enabled` off for the `ci` target on the two marts |
| `dbt/models/semantic/warehouse_credits.yml` | Semantic model and metric |
| `src/retail_pulse/semantic/preset_export.py` | Third dataset |
| `src/retail_pulse/orchestration/dbt_assets.py` | Slowest models from `run_results.json` as a run tag |
| `src/retail_pulse/orchestration/alerts.py`, `definitions.py` | Success sensor for cost and run time |
| `tests/test_alerts.py` (or the existing alerts tests), `tests/test_preset_export.py`, `tests/test_semantic_layer.py`, `tests/test_dbt_environments.py` | See Test strategy |

## Risks and rollback

- **RAW, SCD2 history and the existing marts are not touched**; nothing needs a full refresh.
- **Privilege.** The only new right is read access to usage data, granted by the owner. Until it is
  granted, the two marts fail in dev and prod while everything else builds; the 23:00 run would show
  them red. So the build PR is merged only after the grant (T1 says so), or the marts stay disabled
  until then.
- **Usage delay.** Today's figures are partial; only complete days are compared (R6). If Snowflake's
  delay ever exceeds a day, the "complete" day is still partial and a low figure is missed, never a
  false alarm.
- **Query tag override.** If the project macro does not take precedence, model durations are missing
  but nothing else breaks; T4 checks it before relying on it.
- **Cost of the monitoring itself.** Two small queries per night on usage views, on the existing
  XSMALL warehouse.
- **Rollback:** revert the PR; the two tables stay unused in `MARTS` until dropped by hand; the grant
  can be revoked by the owner.

## Test strategy

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | dbt unit test (hourly rows to daily credits per warehouse, local day); owner: one day compared with Snowsight's warehouse usage page |
| AC2 | dbt unit test on query-history rows with tags; owner: one 23:00 run in `fct_dbt_model_runs` |
| AC3 | dbt unit test of `is_above_threshold` (median, ×2, floor); pytest: sensor posts one message per flagged warehouse (fake Snowflake reader, fake Slack) |
| AC4 | pytest: sensor with fake run records (14 history runs, one slow) posts one message naming duration, threshold and slowest models |
| AC5 | pytest: the sensor never raises or changes a run; Slack down or not configured logs one line |
| AC6 | dbt unit test: today's row has `is_complete_day = false` and is never above threshold |
| AC7 | pytest: parsing the `ci` target excludes the two marts; CI green on the PR |
| AC8 | pytest: the preset ZIP has the credits dataset and metric; owner: chart matches the mart for one day |
| AC9 | Review of `docs/phases/14-cost-monitoring.md` |

## Docs to update

- `docs/Project-Spec.md`: §10.2 (two marts), §11 (success sensor), §12 (chart, third dataset), §13.4
  (the read grant), §14 (phase 14), §17 (the spec's three decisions as Final).
- `docs/phases/14-cost-monitoring.md` (new) and its row in `docs/README.md`; `docs/runbook.md` (what to
  do on a cost or run-time warning); `docs/phases/11-semantic-layer.md` (third dataset).
