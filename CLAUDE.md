# RetailPulse

Batch ELT portfolio project: PostgreSQL 16 (OLTP, Docker) → dlt → Snowflake RAW → dbt (staging,
intermediate SCD2, Kimball marts) → Preset, orchestrated by Dagster, Great Expectations on RAW.

`docs/Project-Spec.md` is the source of truth for scope, data contracts and the decision log. Read the
relevant section before changing behavior. When docs disagree with the spec, the spec wins.

## Commands

- `make install`: `uv sync` (dev tools included). Always run Python through `uv run`.
- `make up`: start Postgres. Needed by `make test`; without it, DB tests are skipped, not failed.
- `make test`: pytest. Creates and drops a disposable `<PG_DB>_test` database.
  `tests/test_orchestration.py` also needs `dbt/target/manifest.json` (run `make dbt-parse` once) and a dbt
  profile; it fails without them.
- `make check`: ruff without fixing, then `make test`. Same as CI. Run it before calling a change done.
- `make dbt-parse`: compiles dbt without querying data. Needs `.env` and `dbt/profiles.yml`.
- `make dbt-build`, `make ingest`, `make dagster`: need a real Snowflake account. Do not run them unless
  the user asks.

Before calling a change done, run `make check` and show the output.

## Rules that are easy to break

- IMPORTANT: Never run `make seed`, `make reseed`, `make db-reset` or `make clean-raw` without the user
  asking. They delete Snowflake RAW, which is the only store of SCD2 history.
- RAW for `product` and `employee` is append-only. Never use `replace`, `merge` or
  `refresh="drop_sources"` on them in dlt.
- SCD2 history is built only in dbt with window functions over RAW. No `dbt snapshot`, and no history
  columns in the Python generators.
- Money is `NUMERIC(12, 2)` in Postgres and `Decimal` in Python. Never write floats to money columns.
- `infras/postgres/init/01_schema.sql` and `src/retail_pulse/oltp/models.py` must stay aligned.
- Analytics use `completed` transactions only. Customer, inventory, returns and Kubernetes are out of scope.
- Never commit secrets: `.env`, `.dlt/secrets.toml`, `dbt/profiles.yml`, `*.p8`, `.snowflake/`.

## Workflow

- Every change reaches `main` through a pull request with green `lint`, `test` and `dbt-slim-ci` checks.
  Fill in the PR template checklist (Definition of Done, spec §16).
  Branch names: `feat/...`, `fix/...`, `docs/...`. Commit messages: `feat: ...`, `fix: ...`, `docs: ...`.
- A new feature (behavior, data contract or Final decision change) starts with `/new-feature` and a
  spec in `specs/NNN-*/` that a person approves before code. Fixes and docs skip it. See `specs/README.md`.
- Review a PR by `REVIEW.md`. Before opening a feature PR, run the `spec-reviewer` subagent and attach its
  report.
- Use plan mode for changes that touch several files or an unfamiliar area. Skip it when the diff fits
  in one sentence.
- A change to a decision marked Final must update the decision log (spec §17), the affected acceptance
  criteria and the docs in the same PR.
- New phase: add `docs/phases/NN-*.md` and a row in the table in `docs/README.md` in the same PR.

## Language

- Everything in the repo is in English: code comments, docstrings, log and CLI messages, docs, dbt
  descriptions, PR descriptions and commit messages.
- Dashboard labels and dbt column values are English only.
