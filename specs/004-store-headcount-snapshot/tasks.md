# 004: Monthly store headcount snapshot, tasks

Plan: [plan.md](plan.md)

- [x] T1: dbt unit tests for `int_employee_daily_store` on hand-made `int_employee_scd2` rows: joiner on
      the 1st, leaver on a month's last day, transfer at 23:30 local, join and transfer on one day,
      transfer after the end date, start before 2020. Run: they fail (model missing).
- [x] T2: Write `int_employee_daily_store.sql` and its docs. T1 passes (`dbt build -s` in dev, or CI).
- [x] T3: dbt unit tests for `fct_store_headcount_monthly`: monthly flows from daily rows, empty
      store-month has zeros, opening of Jan 2020 from 2019-12-31, build month flagged not closed.
      Singular tests for AC1, AC2, AC3, AC4 and AC8. Run: they fail.
- [x] T4: Write `fct_store_headcount_monthly.sql` and its column docs (semi-additive warnings). T3
      passes.
- [x] T5: pytest in `test_semantic_layer.py`: the new metrics exist, `closing_headcount` and
      `opening_headcount` are non-additive on `month_start` (max, min), `revenue_per_employee` is a
      ratio whose SQL has `NULLIF` on the denominator, by-quarter SQL takes the last month. Run: fails.
- [x] T6: Write `dbt/models/semantic/headcount.yml`; `make dbt-parse`. T5 passes.
- [x] T7: pytest in `test_preset_export.py`: the ZIP holds two datasets with fixed uuids, each metric
      on its own dataset, `revenue_per_employee` as one expression, semi-additive metrics as a plain
      sum with warning text. Run: fails.
- [x] T8: Change `preset_export.py` and the `preset-zip` help text. T7 passes.
- [x] T9: `make check` green; CI slim build green on the PR (dbt tests on real data); spec check
      report.
- [x] T10: Docs: `docs/phases/13-headcount-snapshot.md` with the worked example, `docs/README.md` row,
      phases 07 and 11, `design/analytical-data-modeling.md`, Project-Spec §10.2, §10.6, §12, §14, §17.
      Spec status Implemented.
- [ ] T11: Owner, after merge and the 23:00 run: `make preset-zip`, import, build the chart and add it
      to the dashboard (AC10); one `mf query` for a store and quarter (AC9); after a `make stream` and
      the next run, check one transfer (AC5).
