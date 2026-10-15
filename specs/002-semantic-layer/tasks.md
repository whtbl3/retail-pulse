# 002: Semantic layer for metrics, tasks

Plan: [plan.md](plan.md)

- [x] T1: Add `dbt-metricflow` to the dev group (`uv add --group dev`), `uv sync`, check `mf --version`.
- [x] T2: Write `dbt/tests/assert_fct_sales_enriched_matches_fct_sales.sql` (row count, `SUM(net_amount)`,
      `SUM(gross_profit)` equal to `fct_sales`).
- [x] T3: Add `dbt/models/marts/fct_sales_enriched.sql` and its entry in `___models.yml` (every column
      documented, `transaction_id` + `line_number` unique). `make dbt-parse` passes.
- [x] T4: Declare `dim_date` the time spine in `___models.yml`.
- [x] T5: Write `tests/test_semantic_layer.py`: the eight metric names of Q2, each with a label and a
      description; `gross_margin` is a ratio of sums; every metric compiles with `mf query --explain` to
      SQL on `fct_sales_enriched` with no JOIN; every column the semantic model uses is documented on
      `fct_sales_enriched` (plus a case with an unknown column that must fail). Run it: it fails.
- [x] T6: Add `dbt/models/semantic/sales.yml` (semantic model and eight metrics). `mf validate-configs
      --skip-dw` and T5 pass.
- [x] T7: CI: run `mf validate-configs --skip-dw` after `dbt parse` in the `test` job.
- [x] T8: `make preset-zip` builds a Preset dataset import ZIP from the metrics (the API sync needs
      Preset Enterprise; see plan step 4), with `tests/test_preset_export.py`.
- [ ] T9: `make check` green; `spec-reviewer` report; open the PR.
- [ ] T10: Owner, after merge: the 23:00 run (or `make dbt-build`) creates `MARTS.FCT_SALES_ENRICHED`;
      export the `sales_enriched` dataset from Preset, `make preset-zip EXPORT=<zip>`, import the ZIP,
      rebuild the five charts on the metrics, rerun the reconciliation (AC5, AC6, AC7), delete the old
      virtual dataset.
- [x] T11: Docs: `docs/phases/11-semantic-layer.md`, `docs/README.md` row, note in
      `docs/phases/07-preset.md`, Project-Spec §4, §5, §10.2, §10.3, §12, §14, §15 and §17, `CLAUDE.md`,
      `make help`. Spec status Implemented.
