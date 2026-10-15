# 002: Semantic layer for metrics

- Status: Draft
- Intent: none (roadmap step 6, requested by the project owner)
- Project-Spec sections affected: §4, §5, §10.3, §12, §14, §15, §17

## Problem

Every business metric on the dashboard is typed by hand in Preset: each chart picks
`SUM(NET_AMOUNT)` or `SUM(GROSS_PROFIT)` itself (docs/phases/07-preset.md), and gross margin is left to
"the BI layer" (§10.3). A second team or a second tool would define "revenue" again, possibly
differently (gross vs net, with or without coupons), and the numbers would drift. Nothing in the repo
says what a metric means, and no test protects it.

## Goal

Each business metric is defined once, in version control, next to the dbt models it reads. Preset
charts use those definitions instead of hand-written aggregates, so the same question gives the same
number in every chart and to every team.

## Scope

In scope:

- Defining the sales metrics and the dimensions they can be sliced by, as code in the dbt project.
- Validating those definitions in CI.
- Making the defined metrics available in Preset and rebuilding the existing dashboard on them.
- Documenting how to add a metric.

Out of scope:

- Replacing Preset or adding another BI tool.
- New marts, new facts or changes to the grain or keys of `fct_sales` and the dimensions.
- Metrics for domains that are out of scope (§6.2): customers, inventory, returns.
- A paid hosted service, unless open question 1 chooses it.

## Requirements

1. **R1:** Each metric on the dashboard (and the ones listed in open question 2) has exactly one
   definition in the repo, with a name, a description, its formula and the dimensions it can be grouped
   by.
2. **R2:** Metrics only count `completed` transactions, because `fct_sales` only holds them (§10.3); no
   metric adds its own status filter.
3. **R3:** Ratio metrics such as gross margin are computed as a ratio of sums
   (`SUM(gross_profit) / SUM(net_amount)`), never as an average of row-level ratios.
4. **R4:** Product and employee attributes used to slice a metric come from the dimension version that
   was valid at the time of sale (SCD2), as in `fct_sales` today.
5. **R5:** An invalid metric definition (unknown column, missing dimension, broken join) fails CI before
   merge.
6. **R6:** Every chart on `RetailPulse Sales Overview` uses a shared metric, not a hand-written
   aggregate.
7. **R7:** A defined metric gives the same total as the equivalent query on `MARTS.FCT_SALES`, and the
   same total when broken down by category, store or month.
8. **R8:** Preset still reads only `MARTS` through the read-only `REPORTER` role (§12).
9. **R9:** Adding a new metric is documented as a short procedure: define it, validate it, make it
   available in Preset.

## Acceptance criteria

- **AC1:** Given the metric definitions, when CI runs, then they are validated, and a definition that
  references a missing column fails the build.
- **AC2:** Given the `net_revenue` metric, when it is queried for all time, then it equals
  `SUM(net_amount)` from `MARTS.FCT_SALES`.
- **AC3:** Given the `gross_margin` metric, when it is queried by month, then each value equals that
  month's `SUM(gross_profit) / SUM(net_amount)`.
- **AC4:** Given a product whose cost changed during the period, when gross profit is grouped by
  category, then each sale uses the category and cost valid at its transaction time.
- **AC5:** Given the dashboard, when the owner opens any chart's configuration in Preset, then its metric
  is a shared metric and not an ad-hoc SQL aggregate.
- **AC6:** Given a new metric defined by following the documented procedure, when it is made available,
  then it appears in Preset without editing any chart's SQL.
- **AC7:** Given the reconciliation table in docs/phases/07-preset.md, when it is rechecked after the
  change, then the dashboard totals are unchanged.

## Data contract changes

- No change to tables, columns, grain or keys of the marts.
- New: metric and semantic definitions in the dbt project, which become part of the analytics
  contract that Preset reads.
- §10.3 "Ratios such as gross margin are metrics in the BI layer" changes to "metrics in the semantic
  layer".

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Business metrics are defined once with MetricFlow in the dbt project | Proposed | One definition per metric, versioned and validated in CI, next to the models it reads; chosen by the project owner |
| Preset stays the BI tool | Proposed | Owner's choice; the semantic layer serves it, it does not replace it |
| Ratio metrics are ratios of sums | Proposed | An average of row-level ratios weights small sales like large ones and gives a wrong margin |

## Open questions

1. [NEEDS CLARIFICATION] How do the metrics reach Preset? (a) dbt Core only: the definitions are
   synced into the Preset dataset as saved metrics by a command in the repo, free, but Preset does not
   query MetricFlow live; (b) dbt Cloud Semantic Layer, which Preset queries live, but needs a paid dbt
   Cloud plan. Recommended: (a).
2. [NEEDS CLARIFICATION] Which metrics are in the first version? Recommended: the five already on the
   dashboard (`net_revenue`, `gross_revenue`, `discount_amount`, `gross_profit`, `quantity_sold`) plus
   `gross_margin`, `transaction_count` and `average_basket_value`.
3. [NEEDS CLARIFICATION] When are the metrics synced to Preset: by hand with one `make` command after a
   metric changes, or automatically after every `full_pipeline` run? Recommended: by hand, because
   metrics change far less often than data.
4. [NEEDS CLARIFICATION] Is the current dashboard rebuilt on the shared metrics (R6), or kept as is
   with only new charts using them? Recommended: rebuilt.
