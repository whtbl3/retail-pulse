# 002: Semantic layer for metrics, plan

Spec: [spec.md](spec.md)

## Approach

Three layers change: dbt (a wide mart model and the MetricFlow definitions), CI (validation) and
Preset (synced metrics and a rebuilt dashboard). Postgres, dlt, Snowflake RAW and Dagster are not
touched.

**1. One wide model for the metrics to read.** A new mart model `sales_enriched` selects every row
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
- One semantic model `sales` on `sales_enriched`: entity `sale_line` (`transaction_id || '-' ||
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
every column a dimension or measure uses is a documented column of `sales_enriched`; `dbt build` in
`dbt-slim-ci` then proves those documented columns exist.

**4. Sync to Preset (Q1, Q3).** `make preset-sync` runs the sync command of the `preset-cli` tool
(`superset sync dbt-core`) on `dbt/target/manifest.json`, limited to `sales_enriched`. For each metric
it calls `mf query --explain`, converts the SQL into one expression, and saves it as a metric on the
`sales_enriched` dataset. preset-cli pins SQLAlchemy below 2 and the project uses 2.1, so it runs in its
own environment through `uvx`, with the project's `.venv/bin` on `PATH` so it finds `mf`. It needs a
Preset API token in `.env` (`PRESET_API_TOKEN`, `PRESET_API_SECRET`, `PRESET_WORKSPACES`). It does not
use `--import-db`, so it never writes the dbt transformer's credentials into Preset. Instead it finds
the existing `PRESET_READER` connection by name, which must be renamed once to `retail_pulse_dev`
(the name preset-cli derives from the dbt project and target).

**5. Dashboard (Q4, R6).** In Preset, the five charts of `RetailPulse Sales Overview` are rebuilt on
the physical `sales_enriched` dataset with the synced metrics, then the old virtual dataset is
deleted. Doing this by hand once is less work than generating chart definitions, and the steps go in
the phase doc.

## Prototype

Done during planning, then removed from the branch:

- `mf query --explain` with the CI profile and dummy credentials, on a semantic model over a draft
  `sales_enriched`, gave single-table SQL for simple, ratio and derived metrics.
- preset-cli 0.3.13's converter turned that SQL into `SUM(net_amount)`,
  `CAST(SUM(gross_profit) AS DOUBLE) / CAST(NULLIF(SUM(net_amount), 0) AS DOUBLE)` and
  `SUM(net_amount) / NULLIF(COUNT(DISTINCT transaction_id), 0)`.

## Files

| File | Change |
| --- | --- |
| `dbt/models/marts/sales_enriched.sql` | New: `fct_sales` plus slicing attributes, same grain |
| `dbt/models/marts/___models.yml` | `sales_enriched` docs and tests; `dim_date` as the time spine |
| `dbt/models/semantic/sales.yml` | New: semantic model and the eight metrics |
| `dbt/tests/assert_sales_enriched_matches_fct_sales.sql` | New: same row count and same `SUM(net_amount)`, `SUM(gross_profit)` as `fct_sales` |
| `pyproject.toml`, `uv.lock` | Add `dbt-metricflow` to the dev group |
| `.github/workflows/ci.yml` | `mf validate-configs --skip-dw` after `dbt parse` in the `test` job |
| `tests/test_semantic_layer.py` | New: metric list, labels, ratio of sums, single-table SQL |
| `Makefile` | `preset-sync` target |
| `.env.example` | `PRESET_API_TOKEN`, `PRESET_API_SECRET`, `PRESET_WORKSPACES` |

## Risks and rollback

- **RAW and SCD2 history:** untouched. Only a new mart table is added; no full refresh and no RAW
  command.
- **Fan-out or dropped rows in the wide model:** every fact key is non-null (`-1`/`-2` members exist
  in every dimension), so inner joins neither drop nor duplicate rows. A dbt test compares row count
  and totals with `fct_sales` and fails the build if they differ.
- **preset-cli** is a separate tool with an unusual licence ("Other/Proprietary" on PyPI) and old
  SQLAlchemy. It runs only on the owner's machine through `uvx`, is never imported by project code, and
  can be replaced by typing the eight metric expressions in Preset if it breaks.
- **Sync overwrites dataset metrics:** dbt is the source of truth, so metrics added by hand in Preset
  on `sales_enriched` are replaced. The phase doc says so.
- **Metric names that match column names** (`discount_amount`, `gross_profit`): to be checked when
  `mf validate-configs` runs; if MetricFlow rejects them, the measures get a suffix and the metric
  names stay.
- **Rollback:** revert the PR; in Preset, point the charts back to the old virtual dataset (kept until
  the rebuilt dashboard is checked, AC7).

## Test strategy

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | CI `mf validate-configs --skip-dw`; pytest that every column used by the semantic model is a documented column of `sales_enriched` (a test feeds it an unknown column and expects a failure) |
| AC2 | pytest: `net_revenue` compiles to `SUM(net_amount)` on `sales_enriched`; dbt test: `sales_enriched` total equals `fct_sales` |
| AC3 | pytest: `gross_margin` compiles to `SUM(gross_profit) / SUM(net_amount)`, not an average |
| AC4 | `sales_enriched` joins on `product_key`, the SCD2 version key; dbt test on row count and totals; manual check of one product whose cost changed |
| AC5 | Manual: open each chart in Preset, metric is a saved metric |
| AC6 | Manual: add a temporary metric, `make preset-sync`, it appears in Preset; then remove it |
| AC7 | Manual: rerun the reconciliation table in docs/phases/07-preset.md |

## Docs to update

- Project-Spec: §4 (MetricFlow in the stack), §5 (semantic layer in the diagram), §10.2 (the
  `sales_enriched` row), §10.3 (ratios live in the semantic layer), §12 (metrics come from dbt), §14
  (phase 11), §15 (`dbt/models/semantic/`), §17 (the three decisions of the spec, marked Final).
- New `docs/phases/11-semantic-layer.md` and a row in `docs/README.md`: what a semantic layer is, how to
  add a metric, how to sync, and the one-time Preset steps.
- `docs/phases/07-preset.md`: a note that the virtual dataset was replaced in phase 11.
- `make help` and `CLAUDE.md` (`make preset-sync`: talks to Preset, the user runs it).
