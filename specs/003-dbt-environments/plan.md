# 003: Separate dbt development and production, plan

Spec: [spec.md](spec.md)

## Approach

Layers touched: dbt, Dagster, CI (GitHub Actions), local setup. Postgres, dlt, Snowflake RAW and
Great Expectations are not touched.

1. **Three dbt targets with one naming rule (R1, R3, R8).** The custom schema macro changes so that only
   the `prod` target uses the layer name as is (`STAGING`, `INTERMEDIATE`, `MARTS`). Every other target
   uses dbt's default rule, `<target schema>_<layer>`: `dev` writes `DBT_<NAME>_STAGING`,
   `DBT_<NAME>_INTERMEDIATE`, `DBT_<NAME>_MARTS` in `RETAIL_PULSE` (Q1), and `ci` keeps `PR_<n>_*` in
   `RETAIL_PULSE_CI`. The macro refuses to run a non-prod target whose schema is a production schema
   name (`RAW`, `STAGING`, `INTERMEDIATE`, `MARTS`), so a mistyped profile cannot write production.
   The dev schema comes from a new `.env` value `DBT_DEV_SCHEMA` (for example `DBT_PHUCLH`) read with
   `env_var()` without a default: two developers have two names (R8), and a missing value stops dbt
   instead of falling back to a shared schema.

2. **dev is the default; prod needs its name (R4, AC3).** `dbt/profiles.yml.example` gets `target: dev`
   plus a `prod` output with the same user and role. A plain `dbt build` or `make dbt-build` builds dev.
   Production by hand is `make dbt-build-prod` (and `make dbt-full-refresh`, which only makes sense in
   production, passes `--target prod`). Nothing else in the Makefile names prod.

3. **dev builds only what changed (R2, AC1, AC1b, Q2).** `make dbt-build` runs
   `dbt build --select state:modified+ --defer --state <prod state>`, the same mechanism as slim CI.
   The prod state is a `manifest.json` of production made locally by `make dbt-prod-state`: it checks
   out `origin/main` into a git worktree under `dbt/target/` (ignored), links the installed
   `dbt_packages`, and runs `dbt parse --target prod --target-path dbt/target/prod-state`. Parse does
   not query Snowflake. The state has to come from `main`: a manifest of the developer's own tree would
   show nothing as modified. `make dbt-build` runs `dbt-prod-state` first. Unchanged parents and RAW
   resolve to production through `--defer` and are only read. `SELECT=<selector>` overrides the
   selection for a one-off (for example `SELECT=+fct_sales`), still in dev.

4. **Preset grants in the project (R5, AC4, AC4b, Q3, Q4).** `dbt_project.yml` sets `+grants` on
   `marts` only when `target.name == 'prod'`. The list is `select: [REPORTER, CI_RUNNER]`, not REPORTER
   alone: I checked dbt-snowflake 1.12's materializations, and the incremental `fct_sales` revokes every
   grant that is not in the config on each run (`should_revoke` is true when the table is merged into),
   which would remove the `CI_RUNNER` read that slim CI defers to. Table models are replaced and only
   receive the configured grants. With an empty config in dev and CI, `apply_grants` is a no-op (dbt
   core's `default__apply_grants`, "If grant_config is {} or None, this is a no-op"). The manual future
   grant from phase 7 stays as a safety net (Q4).

5. **Dev and CI are not readable by Preset (R6, AC5).** No grant is declared outside prod, and REPORTER
   has `USAGE` only on `RETAIL_PULSE.MARTS` (phase 7), so a `DBT_<NAME>_*` or `PR_<n>_*` schema is not
   reachable. No Snowflake change is needed.

6. **Dagster builds prod (R3, AC2).** `DbtProject(..., target="prod")` so the manifest Dagster loads is
   the production one. The `DbtCliResource(project_dir=dbt_project)` in `definitions.py` inherits that
   target (dagster-dbt `DbtCliResource.__init__` takes `project_dir.target` when none is given), so
   every Dagster `dbt build` runs against prod. The Docker image mounts
   `~/.dbt`, so the owner's profile needs the `prod` output (see Risks).

7. **PR schemas live until the PR closes (R7, AC6).** `drop_ci_schemas` becomes
   `drop_target_schemas`: it drops the current target's default and layer schemas and refuses the
   `prod` target and production schema names. In `ci.yml` the final "Drop the PR schemas" step is
   removed and the same operation runs before the build, so a re-run starts clean. A new workflow
   `.github/workflows/ci-cleanup.yml` runs on `pull_request: types: [closed]` (merge and close both fire
   it) and drops `PR_<n>_*` with the CI profile. `make dbt-dev-clean` runs the same operation on the dev
   target (R9).

8. **Setup and docs (R9, AC7).** `make setup` writes `DBT_DEV_SCHEMA=DBT_<USER>` to `.env` when it is
   missing (from the OS user name, upper case, non-alphanumerics replaced by `_`). An existing
   `~/.dbt/profiles.yml` is never overwritten; if it lacks the `prod` output or the `DBT_DEV_SCHEMA`
   dev schema, setup prints what to add. A new `docs/phases/12-environments.md` explains which command
   uses which environment, the migration, and cleanup.

## Files

| File | Change |
| --- | --- |
| `dbt/macros/generate_schema_name.sql` | Layer name as is only for `prod`; `<schema>_<layer>` elsewhere; refuse production names outside prod |
| `dbt/macros/drop_ci_schemas.sql` → `drop_target_schemas.sql` | Generalised, refuses prod |
| `dbt/dbt_project.yml` | `marts: +grants` for REPORTER and CI_RUNNER when the target is prod |
| `dbt/profiles.yml.example` | `target: dev`, dev schema `env_var('DBT_DEV_SCHEMA')`, new `prod` output |
| `.env.example` | `DBT_DEV_SCHEMA` |
| `src/retail_pulse/setup_local.py` | Write `DBT_DEV_SCHEMA`; note a profile without `prod` |
| `Makefile` | `dbt-prod-state`, slim dev `dbt-build` (+ `SELECT=`), `dbt-build-prod`, `dbt-full-refresh --target prod`, `dbt-dev-clean`; `dbt-test` in dev |
| `dbt/ci/profiles.yml` | prod output default schema `PUBLIC` (was `DBT_DEV`), same as the example |
| `src/retail_pulse/orchestration/dbt_assets.py` | `DbtProject(target="prod")`; `DbtCliResource` inherits it (`definitions.py` comment only) |
| `.github/workflows/ci.yml` | Drop PR schemas before the build, not after |
| `.github/workflows/ci-cleanup.yml` | New: drop `PR_<n>_*` on PR close or merge |
| `tests/test_dbt_environments.py` | New: offline parse checks (see Test strategy) |
| `tests/test_dbt_commands.py` | New: which target each make command and workflow uses (`make -n`, workflow YAML) |
| `docs/phases/11-semantic-layer.md`, `docs/runbook.md` | Commands that now name the dev or prod build |
| `tests/test_setup_local.py`, `tests/test_orchestration.py` | `DBT_DEV_SCHEMA`; Dagster uses prod |

## Risks and rollback

- **RAW, SCD2 history and full refresh are not touched.** No dlt or RAW change, no `make seed`,
  `reseed`, `db-reset` or `clean-raw`. The production schemas keep their names and contents; the first
  prod build after the merge is an ordinary build. `make dbt-full-refresh` only gains `--target prod`.
- **The 23:00 Dagster run needs a `prod` output in `~/.dbt/profiles.yml`.** `make setup` does not
  overwrite an existing profile, so the owner adds it by hand before the next run after the merge
  (the docs give the block to paste). If it is missing, dbt fails at the start with "target prod not
  found": the run fails loudly and production is left as it was, nothing is written to the wrong place.
  Same for `DBT_DEV_SCHEMA` on a developer machine: missing means dbt stops.
- **Grant revocation on `fct_sales`.** Covered in Approach step 4; the test in AC4b also checks
  CI_RUNNER is in the list. If another role ever needs read on the marts, it must be added to the same
  list, or the next incremental run revokes it. Written in phase 12 docs.
- **First dev build with no changes builds nothing.** Expected (Q2); `SELECT=` covers a forced build.
- **Dev schemas accumulate.** `make dbt-dev-clean` drops them; they sit in `RETAIL_PULSE` (Q1) and cost
  storage only.
- **CI cleanup workflow needs secrets on `pull_request` closed.** Same-repo PRs get them; a fork PR's
  cleanup would fail without harm (this repo has no fork contributors).
- **Rollback:** revert the PR. Production schema names never change, so Preset, the semantic layer and
  Dagster keep working on the old code; dev and PR schemas can be dropped by hand.

## Test strategy

Offline pytest, in a new `tests/test_dbt_environments.py`, runs `dbt parse` (no Snowflake connection)
with dummy env vars: the `dev` target from `dbt/profiles.yml.example`, the `ci` and `prod` targets from
`dbt/ci/profiles.yml`, then reads each `manifest.json`. The Snowflake checks need a real account and are
done once by the owner after the merge, written as tasks.

| Acceptance criterion | Proved by |
| --- | --- |
| AC1 | pytest: dev manifest puts every model in `DBT_TEST_*` schemas, none in a production schema. Owner: after `make dbt-build`, `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` of `MARTS` unchanged |
| AC1b | pytest: prod state parsed from the clean project; copy of the project with one staging model edited; `dbt ls -s state:modified+ --state` lists exactly that model and its downstream models |
| AC2 | pytest: Dagster `DbtCliResource` and `DbtProject` target is `prod`. Owner: next 23:00 run rebuilds `MARTS`, no `DBT_*` schema altered |
| AC3 | pytest: parse with the example profile and no `--target` gives target `dev` and developer schemas; `make -n dbt-build` contains no `--target prod` |
| AC4 | Owner: `make dbt-full-refresh` (prod), then as `PRESET_READER` `SELECT count(*) FROM MARTS.FCT_SALES` |
| AC4b | pytest: prod manifest, every model under `models/marts` has `grants.select` containing REPORTER and CI_RUNNER; dev and ci manifests have no grants on any model |
| AC5 | pytest: no grants outside prod (as AC4b). Owner: `USE ROLE REPORTER; SELECT ... FROM DBT_<NAME>_MARTS...` is denied |
| AC6 | pytest: `ci.yml` has no drop step after the build; `ci-cleanup.yml` triggers on `pull_request` `closed` and runs `drop_target_schemas`. Owner: after this PR's CI, `PR_<n>_*` exist; after merge, they are gone |
| AC7 | Review of `docs/phases/12-environments.md` and `make help` against the spec |
| R2 refusal | pytest: a dev target with schema `MARTS` fails to parse with the refusal message; `drop_target_schemas` refuses prod (compile check) |
| R8 | pytest: dev parse without `DBT_DEV_SCHEMA` fails; two names give disjoint schemas |
| R9 | pytest in `test_setup_local.py`: setup writes `DBT_DEV_SCHEMA`, keeps an existing value |

## Docs to update

- `docs/Project-Spec.md`: §10 new subsection "Environments" (targets, schema naming, grants), §11
  (Dagster builds the prod target), §13.4 (grants declared in dbt; REPORTER and CI_RUNNER list), §14
  (phase 12 row), §15 (profiles targets, `ci-cleanup.yml`, `DBT_DEV_SCHEMA`), §17 (decision log rows for
  the four decisions).
- `docs/phases/12-environments.md` (new) and its row in `docs/README.md`.
- `docs/phases/05-dbt.md` (commands now build dev), `06-dagster.md` (prod target), `07-preset.md`
  (grant now declared in dbt; future grant kept as safety net), `09-dataops-ci.md` (PR schemas kept
  until close), `00-environment-setup.md` (`DBT_DEV_SCHEMA`, profile migration).
- `make help` text.
