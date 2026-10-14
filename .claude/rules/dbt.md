---
paths:
  - "dbt/**"
---

# dbt conventions

The model design is in `docs/design/analytical-data-modeling.md` (authoritative) and spec §10.

- Layers: `stg_` (rename, type, dedupe cursor-boundary rows; views) → `int_` (reusable logic such as
  SCD2; tables) → `dim_` / `fct_` (marts; tables). No business logic in staging.
- Every model has an entry in the `___models.yml` of its folder, with a description and column tests.
  Singular tests live in `dbt/tests/assert_<what>.sql` and return the failing rows.
- Surrogate keys use the `surrogate_key` macro (Snowflake `HASH`). `-1` means "No promotion" and `-2`
  means "Unknown"; every dimension has a `-2` member and fact joins `COALESCE` missing keys to `-2`.
- SCD2: a new version only when a tracked column `IS DISTINCT FROM` its `LAG`; the first version is
  valid from `1900-01-01`, the current one to `9999-12-31`. Fact rows join on `transaction_ts` within
  `[valid_from, valid_to)`.
- `fct_sales` is incremental on (`transaction_id`, `line_number`). `date_key` and `time_key` use
  `var('local_tz')`; `transaction_ts` stays UTC.
- Rows stuck on `-2` are fixed with `make dbt-full-refresh`, never by reloading RAW.
- Check a change with `make dbt-parse` at minimum. CI builds `state:modified+` in a separate database.
