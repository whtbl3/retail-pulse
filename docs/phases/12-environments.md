# Phase 12: dbt environments (dev, prod, CI)

Goal: a developer's dbt build never changes what Preset shows; only the scheduled pipeline writes
production.
Spec: [003-dbt-environments](../../specs/003-dbt-environments/spec.md).

## Why it is needed

Until phase 11, `make dbt-build` on a laptop wrote into `STAGING`, `INTERMEDIATE` and `MARTS`, the same
tables Preset reads. An unfinished model built locally replaced the production table at once, and the
dashboard showed it until the next 23:00 run. The read grant Preset needs was a manual step (phase 7),
and CI dropped a PR's schemas right after its run, so nobody could look at what the PR built.

## Which command uses which environment

| Command | Target | Writes to | Builds |
| --- | --- | --- | --- |
| `make dbt-build` | `dev` (default) | `RETAIL_PULSE.DBT_<NAME>_STAGING`, `_INTERMEDIATE`, `_MARTS` | the models you changed and their dependents |
| `make dbt-build SELECT=+fct_sales` | `dev` | same | what `SELECT` names |
| `make dbt-test` | `dev` | same | tests of the models you changed |
| `make dbt-dev-clean` | `dev` | drops your `DBT_<NAME>*` schemas | nothing |
| Dagster `full_pipeline` (23:00) | `prod` | `RETAIL_PULSE.STAGING`, `INTERMEDIATE`, `MARTS` | everything |
| `make dbt-build-prod` | `prod` | same | everything (emergency only) |
| `make dbt-full-refresh` | `prod` | `MARTS.FCT_SALES` | `fct_sales` from scratch |
| CI `dbt-slim-ci` | `ci` | `RETAIL_PULSE_CI.PR_<n>_*` | the PR's changed models and their dependents |

Production is never the default: a command builds prod only if its name says so.

## How it works

```text
                       origin/main ──dbt parse --target prod──▶ dbt/target/prod-state/manifest.json
                                                                          │ (what production looks like)
your branch ──dbt build --select state:modified+ --defer --state ─────────┘
                │
                ├── changed models + dependents ──▶ DBT_PHUCLH_STAGING / _INTERMEDIATE / _MARTS
                └── every other ref() and RAW ────▶ read from production (never written)
```

- **Schema names.** `dbt/macros/generate_schema_name.sql` uses the layer name as is only for `prod`.
  Other targets get dbt's default `<target schema>_<layer>`: `DBT_PHUCLH_MARTS` in dev, `PR_12_MARTS`
  in CI. A non-prod target whose schema is `RAW`, `STAGING`, `INTERMEDIATE` or `MARTS` is refused.
- **Your name.** `DBT_DEV_SCHEMA` in `.env` (for example `DBT_PHUCLH`). `make setup` fills it from your
  user name; the dev profile reads it with `env_var()` and has no default, so a missing value stops dbt
  instead of writing somewhere shared.
- **What changed.** `make dbt-prod-state` checks out `origin/main` into a temporary git worktree and
  parses it for the prod target (no query), the same file CI downloads from `manifest.yml`. It has to
  come from `main`: a manifest of your own branch would show nothing as changed. With no change, a dev
  build builds nothing; use `SELECT=` to force one.
- **Grants.** `dbt_project.yml` gives `SELECT` on every mart to `REPORTER` (Preset) and `CI_RUNNER` (slim
  CI reads the marts through `--defer`), only when the target is `prod`. dbt reapplies them after every
  prod build, including a full refresh. The list must name **every** role that reads the marts: the
  incremental `fct_sales` revokes, on each run, any grant that is not in it (dbt-snowflake
  `should_revoke`). Dev and CI declare none, and `REPORTER` has no `USAGE` on their schemas. The manual
  `FUTURE TABLES` grant from [phase 7](07-preset.md) stays as a safety net.
- **PR schemas.** CI drops a PR's schemas *before* its build (a re-run starts clean) and keeps them
  after, so reviewers can query `RETAIL_PULSE_CI.PR_<n>_*`. `.github/workflows/ci-cleanup.yml` drops
  them when the PR is merged or closed. `drop_target_schemas` refuses the prod target and production
  schema names.

## Migration for an existing machine

`make setup` never overwrites `~/.dbt/profiles.yml`. On a machine set up before this phase:

1. `make setup` adds `DBT_DEV_SCHEMA` to `.env` (or add it yourself, `DBT_<YOURNAME>`).
2. In `~/.dbt/profiles.yml`, under `retail_pulse: outputs:`, change the dev schema and add `prod`, as in
   `dbt/profiles.yml.example`:

   ```yaml
       dev:
         # ...unchanged...
         schema: "{{ env_var('DBT_DEV_SCHEMA') }}"
       prod:
         type: snowflake
         account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
         user: DBT_TRANSFORMER
         role: TRANSFORMER
         private_key_path: "{{ env_var('DBT_PRIVATE_KEY_PATH') }}"
         database: RETAIL_PULSE
         warehouse: RETAIL_WH
         schema: PUBLIC
         threads: 4
   ```

3. `make dagster-up` so the always-on Dagster picks up the new code. **Do it before the next 23:00
   run:** Dagster now asks for the `prod` target; without it, the run fails at its first dbt step and
   production stays as it was.

## Verify

```bash
make dbt-build                      # change one staging model first
```

- The log lists only that model and its downstream models, in `DBT_<NAME>_*` schemas.
- In Snowsight, `MARTS` tables keep their `LAST_ALTERED` time:
  `SELECT table_name, last_altered FROM RETAIL_PULSE.INFORMATION_SCHEMA.TABLES WHERE table_schema = 'MARTS';`
- As `REPORTER`, `SELECT * FROM RETAIL_PULSE.DBT_<NAME>_MARTS.FCT_SALES` is denied.
- After `make dbt-full-refresh`, `PRESET_READER` can still query `MARTS.FCT_SALES`.
- After a PR is merged or closed, its `PR_<n>_*` schemas are gone from `RETAIL_PULSE_CI`.

Clean up your dev schemas with `make dbt-dev-clean`.

Further reading: [dbt: custom schemas](https://docs.getdbt.com/docs/build/custom-schemas),
[dbt: defer](https://docs.getdbt.com/reference/node-selection/defer),
[dbt: grants](https://docs.getdbt.com/reference/resource-configs/grants).
