# 005: Enforced contracts on the marts, plan

Spec: [spec.md](spec.md)

## Approach

Layers touched: dbt (model YAML, one config), pytest, docs. No SQL of any model changes; Postgres, dlt,
RAW, Dagster jobs and Preset are not touched.

1. **Contracts on all 10 marts (R1, R2, Q1).** In `dbt/models/marts/___models.yml` every mart gets
   `config: {contract: {enforced: true}}` and every column a `data_type`. `dbt_project.yml` is not
   used for this, so a reader sees the contract next to the columns. With the contract on, dbt
   compares the model's query result with the declared columns before it creates the table and stops
   with a table of mismatches (name, declared type, actual type) when they differ.
2. **Types come from what the models return today (R4).** Each column is declared with the type
   Snowflake gives it now: `NUMBER(38,0)` or the surrogate-key type of `HASH` for keys, `NUMBER(p,s)`
   for money and averages, `DATE`, `TIMESTAMP_TZ`, `VARCHAR`, `BOOLEAN`. The first CI build is the
   check: if any declaration is off, dbt prints the actual type and the declaration is corrected
   before review. Nothing in the SQL is cast to fit a declaration, so the data and column types stay
   what they are (AC4).
3. **Not null where it is already tested (R3).** Columns with a `not_null` test get
   `constraints: [{type: not_null}]`. In the installed dbt-snowflake (`impl.py`), `not_null` is the only
   constraint Snowflake enforces; `unique`, `primary_key` and `foreign_key` are recorded but not
   enforced, so the existing `unique` and `relationships` tests stay (spec decision 2). The `-2`
   Unknown members fill every not-null column today (the tests pass), so no row breaks the rule.
4. **The incremental fact (R5).** dbt refuses a contract on an incremental model unless
   `on_schema_change` is `append_new_columns` or `fail` (checked in
   `dbt/artifacts/resources/v1/config.py`). `fct_sales` gets `on_schema_change='fail'`: a normal
   incremental run is unchanged (same columns), and a shape change stops the run instead of silently
   altering the table; adding a column on purpose then needs the existing full-refresh job, which
   the docs say.
5. **No mart without a contract (R6).** A pytest in `tests/test_dbt_environments.py` (which already
   parses the project offline) checks that every model under `models/marts` has
   `contract.enforced = true` and a `data_type` on every column. It runs in CI's `test` job, so a new
   mart without a declared shape fails there and the message names it (AC6).
6. **Docs (R7).** A "Mart contracts" subsection in Project-Spec §10, a section in
   `docs/phases/05-dbt.md` (what a contract is, the not-null limits on Snowflake, how to add a column:
   SQL + YAML in one PR, and the `fct_sales` full refresh).

## Files

| File | Change |
| --- | --- |
| `dbt/models/marts/___models.yml` | `contract.enforced`, `data_type` on every column, `not_null` constraints |
| `dbt/models/marts/fct_sales.sql` | `on_schema_change='fail'` in the config block |
| `tests/test_dbt_environments.py` | Every mart has an enforced contract and typed columns |
| `docs/Project-Spec.md`, `docs/phases/05-dbt.md` | Contract rule and how to change a mart's shape |

## Risks and rollback

- **RAW and SCD2 history are not touched.** No model SQL changes, no full refresh is needed to deploy:
  with the contract on, dbt creates the table models with an explicit column list on the next run,
  same names and types. `fct_sales` keeps merging incrementally.
- **A wrong declared type stops the build.** That is the point, and CI catches it before merge
  because slim CI builds the changed marts (every mart is "modified" in this PR, so CI builds all 10).
- **Dimension changes later cost one more line.** Expected (spec goal).
- **Rollback:** revert the PR; the next run recreates the tables as before.

## Test strategy

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | pytest: offline parse, every mart has `contract.enforced` and every column a `data_type` |
| AC2 | CI demonstration on this PR: one commit renames a column in a copy of the SQL without the YAML, `dbt-slim-ci` fails naming it; the commit is reverted and both runs are linked in the PR |
| AC3 | Same demonstration with a cast to another type |
| AC4 | CI builds all 10 marts with the contracts and all existing tests pass (row counts in the CI log); owner: after the 23:00 run, `LAST_ALTERED` changed and row counts as the day before |
| AC5 | Owner: the 23:00 run log shows `fct_sales` merged, not recreated |
| AC6 | pytest above, with a parse of a project copy that adds a mart without a contract |
| AC7 | Review of the docs |

## Docs to update

- `docs/Project-Spec.md`: new §10.7 "Mart contracts", §13.3 (contracts listed with the tests), §17 (the
  two decisions as Final).
- `docs/phases/05-dbt.md`: "Mart contracts" section.
