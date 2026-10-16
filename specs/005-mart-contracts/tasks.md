# 005: Enforced contracts on the marts, tasks

Plan: [plan.md](plan.md)

- [ ] T1: pytest: every model under `models/marts` has an enforced contract and a `data_type` on every
      column; a project copy with an extra mart without one fails. Run: fails.
- [ ] T2: Declare contracts, types and `not_null` constraints in `marts/___models.yml`;
      `on_schema_change='fail'` on `fct_sales`. `dbt parse` and T1 pass.
- [ ] T3: Push; fix any declared type the first `dbt-slim-ci` run reports as different.
- [ ] T4: AC2 and AC3 demonstration on the PR (renamed column, changed type), linked, then reverted.
- [ ] T5: `make check` green; spec check report.
- [ ] T6: Docs: Project-Spec §10.7, §13.3, §17; `docs/phases/05-dbt.md`. Spec status Implemented.
- [ ] T7: Owner, after merge: the 23:00 run is green and `fct_sales` merged incrementally (AC4, AC5).
