# 002: Semantic layer for metrics, tasks

Plan: [plan.md](plan.md)

- [ ] T1: Add `dbt-metricflow` to the dev group (`uv add --group dev`), `uv sync`, check `mf --version`.
- [ ] T2: Write `dbt/tests/assert_sales_enriched_matches_fct_sales.sql` (row count, `SUM(net_amount)`,
      `SUM(gross_profit)` equal to `fct_sales`).
- [ ] T3: Add `dbt/models/marts/sales_enriched.sql` and its entry in `___models.yml` (every column
      documented, `transaction_id` + `line_number` unique). `make dbt-parse` passes.
- [ ] T4: Declare `dim_date` the time spine in `___models.yml`.
- [ ] T5: Write `tests/test_semantic_layer.py`: the eight metric names of Q2, each with a label and a
      description; `gross_margin` is a ratio of sums; every metric compiles with `mf query --explain` to
      SQL on `sales_enriched` with no JOIN; every column the semantic model uses is documented on
      `sales_enriched` (plus a case with an unknown column that must fail). Run it: it fails.
- [ ] T6: Add `dbt/models/semantic/sales.yml` (semantic model and eight metrics). `mf validate-configs
      --skip-dw` and T5 pass.
- [ ] T7: CI: run `mf validate-configs --skip-dw` after `dbt parse` in the `test` job.
- [ ] T8: `make preset-sync` and the three `PRESET_*` lines in `.env.example`.
- [ ] T9: `make check` green; `spec-reviewer` report; open the PR.
- [ ] T10: Owner, after merge: `make dbt-build` (or wait for the 23:00 run) so `MARTS.SALES_ENRICHED`
      exists, rename the Preset database to `retail_pulse_dev`, `make preset-sync`, rebuild the five
      charts on the synced metrics, rerun the reconciliation (AC5, AC6, AC7), delete the old virtual
      dataset.
- [ ] T11: Docs: `docs/phases/11-semantic-layer.md`, `docs/README.md` row, note in
      `docs/phases/07-preset.md`, Project-Spec §4, §5, §10.2, §10.3, §12, §14, §15 and §17, `CLAUDE.md`,
      `make help`. Spec status Implemented.
