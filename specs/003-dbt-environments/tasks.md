# 003: Separate dbt development and production, tasks

Plan: [plan.md](plan.md)

- [x] T1: Write `tests/test_dbt_environments.py` with an offline `dbt parse` helper (dummy env vars,
      `--target-path` in `tmp_path`) and the schema tests: dev puts every model in `DBT_TEST_*`
      (AC1, AC3), prod keeps `STAGING`/`INTERMEDIATE`/`MARTS`, ci keeps `PR_<n>_*`, a dev schema named
      `MARTS` is refused, a missing `DBT_DEV_SCHEMA` fails (R8). Run: they fail.
- [x] T2: Change `generate_schema_name.sql`; add `DBT_DEV_SCHEMA` to `profiles.yml.example` (dev
      default, new prod output) and `.env.example`. T1 passes.
- [x] T3: Test the grants (AC4b, AC5): prod marts grant `select` to REPORTER and CI_RUNNER; dev and ci
      have none. Run: fails.
- [x] T4: Add the conditional `+grants` to `dbt_project.yml`. T3 passes.
- [x] T5: Test AC1b: prod state from the clean project, one staging model edited in a copy,
      `dbt ls -s state:modified+` lists exactly it and its downstream models. Run: passes on the
      mechanism; it guards the Makefile selection in T6.
- [x] T6: Makefile: `dbt-prod-state` (origin/main worktree, `dbt parse --target prod`), slim dev
      `dbt-build` with `SELECT=`, `dbt-build-prod`, `dbt-full-refresh --target prod`, `dbt-dev-clean`;
      `make help` text. Test: `make -n dbt-build` names no prod target, `make -n dbt-full-refresh`
      does.
- [x] T7: Test that `drop_target_schemas` refuses prod; rename and generalise the macro.
- [x] T8: Test that Dagster's dbt resource and project use target `prod` (AC2); set `target="prod"` in
      `dbt_assets.py` and `definitions.py`.
- [x] T9: Test the workflows (AC6): no drop step after the build in `ci.yml`, drop before it;
      `ci-cleanup.yml` on `pull_request` `closed`. Then change `ci.yml` and add `ci-cleanup.yml`.
- [x] T10: Test `make setup` writes `DBT_DEV_SCHEMA` and keeps an existing one, and notes a profile with
      no `prod` output (R9); change `setup_local.py`.
- [x] T11: `make check` (ruff + pytest) green; `spec-reviewer` report; ready the PR.
- [ ] T12: Owner, before the first 23:00 run after merge: add the `prod` output and `DBT_DEV_SCHEMA`
      to `~/.dbt/profiles.yml` and `.env`. After it: check AC1 (`make dbt-build`, MARTS last-altered
      unchanged), AC2 (23:00 run), AC4 (`make dbt-full-refresh`, PRESET_READER query), AC5 (REPORTER
      denied on `DBT_<NAME>_MARTS`), AC6 (this PR's `PR_<n>_*` gone after merge).
- [x] T13: Docs: `docs/phases/12-environments.md`, `docs/README.md` row, notes in phases 00, 05, 06, 07
      and 09, Project-Spec §10, §11, §13.4, §14, §15 and §17, `CLAUDE.md` commands. Spec status
      Implemented.
