# 006: Warehouse cost and run time monitoring, tasks

Plan: [plan.md](plan.md)

- [ ] T1: Check in Snowflake's docs which database role covers `WAREHOUSE_METERING_HISTORY` and
      `QUERY_HISTORY`; write the grant in `init.sql` (commented) and send it to the owner. Owner runs
      it before the build PR is merged.
- [ ] T2: dbt unit tests for `fct_warehouse_credits_daily` (daily sum in local time, complete day,
      median of 14, ×2, floor). Run: fail.
- [ ] T3: Source and `fct_warehouse_credits_daily` with contract and docs. T2 passes in dev.
- [ ] T4: Query tag macro; `dbt compile` shows the tag on a model; dbt unit test for
      `fct_dbt_model_runs`; write the mart. Passes in dev.
- [ ] T5: pytest: `ci` target parse excludes both marts; `enabled` config. Passes.
- [ ] T6: pytest for the success sensor (run time, credits, Slack down, no webhook); slowest models
      from `run_results.json` in the dbt asset. Then the code. Passes.
- [ ] T7: Semantic model and metric; pytest for the third Preset dataset; `preset_export.py`. Passes.
- [ ] T8: `make check` green; CI green; spec check report.
- [ ] T9: Docs: phase 14 guide, `docs/README.md`, runbook, phase 11, Project-Spec sections. Spec status
      Implemented.
- [ ] T10: Owner, after merge and the 23:00 run: compare one day of credits with Snowsight (AC1), check
      one run in `fct_dbt_model_runs` (AC2), import the ZIP and build the chart (AC8).
