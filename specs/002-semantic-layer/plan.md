# 002: Semantic layer for metrics, plan

Spec: [spec.md](spec.md)

## Approach

Three layers change: dbt (a wide mart model and the MetricFlow definitions), CI (validation) and
Preset (synced metrics and a rebuilt dashboard). Postgres, dlt, Snowflake RAW and Dagster are not
touched.

**1. One wide model for the metrics to read.** Named `fct_sales_enriched` to follow the `fct_`/`dim_`
convention of §10.2 (owner's choice during the build). A new mart model `fct_sales_enriched` selects every row
of `fct_sales` and adds the attributes the charts slice by: `full_date`, `store_name`,
`category_name`, `brand_name`, `promotion_label`, `payment_method_name`. It joins on the fact's
surrogate keys, so a product or employee attribute is the version that was valid at the time of sale
(R4) with no new range join. It is a table in `MARTS` like the other marts, so the existing
`FUTURE TABLES` grant gives `REPORTER` read access (R8). It replaces the SQL that the Preset virtual
dataset `sales_enriched` holds today, so the join logic moves into the repo.

Why a wide model instead of MetricFlow joining the fact to the dimensions itself: the sync tool turns
each metric into one SQL expression on one dataset, and it rejects metrics whose SQL has a JOIN. A
prototype confirmed that metrics on a single model convert cleanly (see "Prototype" below).

**2. MetricFlow definitions.** `dbt-metricflow` is added to the dev dependencies (it resolves with
dbt-core 1.12 and the current lock). In `dbt/models/semantic/`:

- `dim_date` is declared the time spine (`time_spine` on the model, `granularity: day` on
  `full_date`); MetricFlow refuses to run without one.
- One semantic model `sales` on `fct_sales_enriched`: entity `sale_line` (`transaction_id || '-' ||
  line_number`), time dimension `full_date`, categorical dimensions for the other attributes, and the
  measures.
- The eight metrics of Q2, each with a label and a description:

| Metric | Type | Definition |
| --- | --- | --- |
| `net_revenue` | simple | `SUM(net_amount)` |
| `gross_revenue` | simple | `SUM(gross_amount)` |
| `discount_amount` | simple | `SUM(discount_amount)` |
| `gross_profit` | simple | `SUM(gross_profit)` |
| `quantity_sold` | simple | `SUM(quantity)` |
| `transaction_count` | simple | `COUNT(DISTINCT transaction_id)` |
| `gross_margin` | ratio | `gross_profit / net_revenue`, a ratio of sums (R3) |
| `average_basket_value` | derived | `net_revenue / NULLIF(transaction_count, 0)` |

No metric filters on status: `fct_sales` only holds `completed` rows (R2).

**3. Validation in CI (R5).** The `test` job already runs `dbt parse`. It adds
`mf validate-configs --skip-dw`, which checks the semantic definitions without a warehouse, and pytest
compiles every metric with `mf query --explain`. Both run offline: the prototype compiled all metrics
with the CI profile and dummy credentials. `--skip-dw` does not see columns, so pytest also checks that
every column a dimension or measure uses is a documented column of `fct_sales_enriched`; `dbt build` in
`dbt-slim-ci` then proves those documented columns exist.

**4. Getting the metrics into Preset (Q1, Q3).** Changed during the build: the plan first used the
`preset-cli` sync command, but it needs the Preset API, which only the Enterprise plan has ("The Preset
API is only available for the Enterprise plan", api-docs.preset.io; the free tier lists no "API
access", docs.preset.io/docs/free-tier-limits). The owner chose a ZIP import instead:

- `make preset-zip EXPORT=<zip>` builds `dbt/target/preset_fct_sales_enriched.zip`. The input is a
  dataset export the owner downloads once from Preset (Data > Datasets > select a dataset > Export).
  From it the command copies `metadata.yaml` and the database file unchanged, so the bundle matches the
  owner's Preset version and points at the existing `PRESET_READER` connection. Superset's dataset
  importer calls `import_database(config, overwrite=False)`, which returns the existing database when
  the uuid matches (`superset/commands/dataset/importers/v1/__init__.py`), so the connection and its
  password are never changed.
- Each metric's SQL comes from `mf query --explain` and is reduced to one expression with sqlglot,
  the same reduction preset-cli does; derived metrics get their subquery aliases inlined.
- The dataset uuid is fixed (uuid5 of the model name), so importing a new ZIP updates the same dataset.
- The owner imports it in Preset (Data > Datasets > Import). No API key, no new secret.

**5. Dashboard (Q4, R6).** In Preset, the five charts of `RetailPulse Sales Overview` are rebuilt on
the physical `fct_sales_enriched` dataset with the synced metrics, then the old virtual dataset is
deleted. Doing this by hand once is less work than generating chart definitions, and the steps go in
the phase doc.

## Prototype

Done during planning, then removed from the branch:

- `mf query --explain` with the CI profile and dummy credentials, on a semantic model over a draft
  `fct_sales_enriched`, gave single-table SQL for simple, ratio and derived metrics.
- preset-cli 0.3.13's converter turned that SQL into `SUM(net_amount)`,
  `CAST(SUM(gross_profit) AS DOUBLE) / CAST(NULLIF(SUM(net_amount), 0) AS DOUBLE)` and
  `SUM(net_amount) / NULLIF(COUNT(DISTINCT transaction_id), 0)`.

## Files

| File | Change |
| --- | --- |
| `dbt/models/marts/fct_sales_enriched.sql` | New: `fct_sales` plus slicing attributes, same grain |
| `dbt/models/marts/___models.yml` | `fct_sales_enriched` docs and tests; `dim_date` as the time spine |
| `dbt/models/semantic/sales.yml` | New: semantic model and the eight metrics |
| `dbt/tests/assert_fct_sales_enriched_matches_fct_sales.sql` | New: same row count and same `SUM(net_amount)`, `SUM(gross_profit)` as `fct_sales` |
| `pyproject.toml`, `uv.lock` | Add `dbt-metricflow` to the dev group |
| `.github/workflows/ci.yml` | `mf validate-configs --skip-dw` after `dbt parse` in the `test` job |
| `tests/test_semantic_layer.py` | New: metric list, labels, ratio of sums, single-table SQL |
| `src/retail_pulse/semantic/preset_export.py` | New: builds the Preset import ZIP |
| `tests/test_preset_export.py` | New: expression reduction, bundle content, stable uuids, bad exports |
| `Makefile` | `preset-zip` target |

## Risks and rollback

- **RAW and SCD2 history:** untouched. Only a new mart table is added; no full refresh and no RAW
  command.
- **Fan-out or dropped rows in the wide model:** every fact key is non-null (`-1`/`-2` members exist
  in every dimension), so inner joins neither drop nor duplicate rows. A dbt test compares row count
  and totals with `fct_sales` and fails the build if they differ.
- **Import format drift:** the bundle copies `metadata.yaml`, the database file and the dataset keys
  from the owner's own export, so it follows their Preset version. If an import still fails, the error
  names the field; the metrics can also be typed by hand from `make preset-zip` output as a fallback.
- **Import overwrites dataset metrics:** dbt is the source of truth, so metrics added by hand in
  Preset on `fct_sales_enriched` are replaced. The phase doc says so.
- **Metric names that match column names** (`discount_amount`, `gross_profit`): to be checked when
  `mf validate-configs` runs; if MetricFlow rejects them, the measures get a suffix and the metric
  names stay.
- **Rollback:** revert the PR; in Preset, point the charts back to the old virtual dataset (kept until
  the rebuilt dashboard is checked, AC7).

## Test strategy

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | CI `mf validate-configs --skip-dw`; pytest that every column used by the semantic model is a documented column of `fct_sales_enriched` (a test feeds it an unknown column and expects a failure) |
| AC2 | pytest: `net_revenue` compiles to `SUM(net_amount)` on `fct_sales_enriched`; dbt test: `fct_sales_enriched` total equals `fct_sales` |
| AC3 | pytest: `gross_margin` compiles to `SUM(gross_profit) / SUM(net_amount)`, not an average |
| AC4 | `fct_sales_enriched` joins on `product_key`, the SCD2 version key; dbt test on row count and totals; manual check of one product whose cost changed |
| AC5 | Manual: open each chart in Preset, metric is a saved metric |
| AC6 | pytest: a metric in the semantic manifest appears in the bundle; manual: add a temporary metric, `make preset-zip`, import, it appears in Preset; then remove it |
| AC7 | dbt: unique (`transaction_id`, `line_number`) plus equal row count and totals means each fact row appears once, so totals by category, store or month match too (R7); manual: rerun the reconciliation table in docs/phases/07-preset.md |

## Docs to update

- Project-Spec: §4 (MetricFlow in the stack), §5 (semantic layer in the diagram), §10.2 (the
  `fct_sales_enriched` row), §10.3 (ratios live in the semantic layer), §12 (metrics come from dbt), §14
  (phase 11), §15 (`dbt/models/semantic/`), §17 (the three decisions of the spec, marked Final).
- New `docs/phases/11-semantic-layer.md` and a row in `docs/README.md`: what a semantic layer is, how to
  add a metric, how to sync, and the one-time Preset steps.
- `docs/phases/07-preset.md`: a note that the virtual dataset was replaced in phase 11.
- `make help` and `CLAUDE.md` (`make preset-zip`).

## Changes during the build

- The wide model is `fct_sales_enriched`, not `sales_enriched`, to follow the §10.2 naming convention
  (owner's choice).
- Preset gets the metrics through a ZIP import instead of `preset-cli` sync: the Preset API is
  Enterprise only (step 4).
- `fct_sales_enriched` also keeps `year`, `month`, `month_name`, `day_name`, `is_weekend` and
  `promotion_type`, which the old virtual dataset exposed, so existing filters keep working.
