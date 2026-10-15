# Phase 11: Semantic layer (MetricFlow metrics in Preset)

Goal: every business metric is defined once, in the repo, and every Preset chart uses that definition.
Spec: [002-semantic-layer](../../specs/002-semantic-layer/spec.md).

## Why it is needed

Until phase 10, each chart in Preset typed its own aggregate (`SUM(NET_AMOUNT)`, `SUM(GROSS_PROFIT)`),
and gross margin existed nowhere. A second team or tool would define "revenue" again, maybe as gross
instead of net, and the numbers would drift. A semantic layer is the shared menu of recipes: each metric
has one name, one description and one formula, and every tool orders from it.

## What runs where

```text
fct_sales + dim_*  ──dbt──▶  fct_sales_enriched  (same grain, dimension attributes joined in)
                                    │
             dbt/models/semantic/sales.yml  (semantic model "sales" + 8 metrics, MetricFlow)
                                    │  mf query --explain  →  one SQL expression per metric
                                    ▼
          make preset-zip  ──▶  dbt/target/preset_datasets.zip  ──import──▶  Preset
```

| Piece | Does |
| --- | --- |
| `dbt/models/marts/fct_sales_enriched.sql` | `fct_sales` joined to its dimensions on surrogate keys, so product attributes are the version valid at the time of sale. A dbt test checks it has the same rows and totals as `fct_sales` |
| `dbt/models/semantic/sales.yml` | The metrics. Change a metric here, never in Preset |
| `dim_date` in `___models.yml` | Declared the MetricFlow time spine |
| `src/retail_pulse/semantic/preset_export.py` | Builds the import ZIP (`make preset-zip`) |
| CI `test` job | `mf validate-configs --skip-dw`, then pytest compiles every metric |

Why a wide model and not MetricFlow joins: Preset stores a metric as one SQL expression on one dataset,
so a metric that needs a join cannot be copied into it. Kimball's star schema is unchanged; the wide
model is a presentation layer on top of it, the same join the Preset virtual dataset `sales_enriched`
used to hold.

## The metrics

| Metric | Formula |
| --- | --- |
| `net_revenue` | `SUM(net_amount)` |
| `gross_revenue` | `SUM(gross_amount)` |
| `discount_amount` | `SUM(discount_amount)` (promotions, not coupons) |
| `gross_profit` | `SUM(gross_profit)` |
| `quantity_sold` | `SUM(quantity)` |
| `transaction_count` | `COUNT(DISTINCT transaction_id)` |
| `gross_margin` | `SUM(gross_profit) / SUM(net_amount)`, a ratio of sums |
| `average_basket_value` | `net_revenue / transaction_count` |

`fct_sales` only holds `completed` transactions, so no metric filters on status.

List them with their dimensions:

```bash
cd dbt && uv run mf list metrics
uv run mf query --metrics net_revenue --group-by sale_line__store_name --explain   # the SQL, no query
```

## Getting the metrics into Preset

The Preset API, which a direct sync would need, is only available on the Enterprise plan
([The Preset API](https://docs.preset.io/docs/the-preset-api)). On other plans the metrics go in as a
dataset import.

Once, after `MARTS.FCT_SALES_ENRICHED` exists (the 23:00 run, or `make dbt-build-prod`):

1. **Export a dataset that uses the Snowflake connection.** In Preset, **Data > Datasets**, hover over
   `sales_enriched`, click the Export icon under **Actions**
   ([Migrating Datasets](https://docs.preset.io/docs/migrating-datasets)). Keep the ZIP outside the repo:
   it holds the connection string (password masked). From WSL, Windows downloads are under
   `/mnt/c/Users/<you>/Downloads/`.
2. **Build the import ZIP:**

   ```bash
   make preset-zip EXPORT=/mnt/c/Users/<you>/Downloads/<export>.zip
   ```

   It writes `dbt/target/preset_datasets.zip`: your export's `metadata.yaml` and database file
   unchanged, plus the `FCT_SALES_ENRICHED` dataset with the 8 sales metrics and, since
   [phase 13](13-headcount-snapshot.md), the `FCT_STORE_HEADCOUNT_MONTHLY` dataset with the headcount
   metrics.
3. **Import it:** **Data > Datasets**, the Import icon at the top right, choose the ZIP, confirm. The
   dataset is attached to the existing connection: Superset reuses a database with the same uuid and
   does not change it during a dataset import.
4. **Rebuild the charts** of `RetailPulse Sales Overview` on the `FCT_SALES_ENRICHED` dataset. In each
   chart, pick the metric from the **Saved** tab of the metric picker instead of a `SUM(...)`:

   | Chart | Metric(s) |
   | --- | --- |
   | Net revenue by month | `net_revenue` |
   | Net revenue by category | `net_revenue` |
   | Net revenue by store | `net_revenue` |
   | Promotion impact | `net_revenue`, `discount_amount` |
   | Gross profit by month | `gross_profit` |

5. **Check the numbers** with the reconciliation table in [phase 7](07-preset.md#reconciling-numbers-with-the-warehouse):
   totals must not change. Then delete the old `sales_enriched` virtual dataset.

### Changing or adding a metric

1. Edit `dbt/models/semantic/sales.yml`. Add the name to `EXPECTED_METRICS` in
   `tests/test_semantic_layer.py` and its expression to `EXPECTED` in `tests/test_preset_export.py`.
2. `make check`, then a PR as usual.
3. After merge: `make preset-zip EXPORT=...` with the same export, import, confirm the overwrite. The
   dataset keeps its uuid, so charts keep working.

Metrics added by hand in Preset on `FCT_SALES_ENRICHED` are replaced by the next import.

## Verify

| Check | How | Spec |
| --- | --- | --- |
| Definitions valid | CI `mf validate-configs --skip-dw`; `tests/test_semantic_layer.py` | AC1 |
| Net revenue and gross margin formulas | `tests/test_semantic_layer.py`, `tests/test_preset_export.py` | AC2, AC3 |
| Same rows and totals as `fct_sales` | dbt test `assert_fct_sales_enriched_matches_fct_sales` | AC4, AC7 |
| Charts use saved metrics | Open each chart in Preset | AC5 |
| New metric reaches Preset | Add one, `make preset-zip`, import | AC6 |
| Dashboard totals unchanged | Phase 7 reconciliation | AC7 |
