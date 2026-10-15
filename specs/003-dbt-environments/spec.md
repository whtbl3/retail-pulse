# 003: Separate dbt development and production

- Status: Draft (all questions answered, awaiting approval)
- Intent: none (requested by the project owner after the dbt topics review)
- Project-Spec sections affected: §10 (new subsection on environments), §11, §13.4, §14, §15, §17

## Problem

A developer who builds dbt models on their own machine writes into the same Snowflake schemas
(`STAGING`, `INTERMEDIATE`, `MARTS`) that the scheduled pipeline builds and Preset reads. An unfinished
model built locally replaces the production table at once, and the dashboard shows it until the next
23:00 run. Only CI has its own place (one schema set per pull request).

The read access Preset needs on the marts is granted by hand once (phase 7 setup), outside
the code, so a new environment or a rebuilt database silently loses it. CI drops a pull request's
schemas at the end of every run, so nobody can inspect what a PR built.

## Goal

Each developer builds into their own schemas and cannot change what Preset shows. Only the scheduled
pipeline writes production. The read grants Preset depends on are part of the dbt project and are
reapplied on every production build. A pull request's CI schemas exist while the PR is open and are
removed when it is merged or closed.

## Scope

In scope:

- A development environment per developer, separate from production, used by default on a developer
  machine.
- A production environment used only by the scheduled pipeline (and by an explicit, documented manual
  command for emergencies).
- Read grants for the Preset role on production marts, declared in the dbt project.
- CI schemas kept for the life of a pull request and dropped when it is merged or closed.
- Docs and setup so a new developer gets their own environment from the first-time setup.

Out of scope:

- A separate staging/QA environment between dev and prod.
- Multiple Snowflake accounts.
- Changing production schema names, so Preset, Dagster and the semantic layer keep reading the same
  tables.
- Any change to RAW, its load strategies or SCD2 history.

## Requirements

1. **R1:** On a developer machine, a dbt build without extra options writes only to that developer's own
   schemas, whose names identify the developer and the layer.
2. **R2:** A development build builds only the models the developer changed and the models that depend
   on them; every other model, and RAW, is read from production (read only). It never creates,
   replaces or drops anything in the production `STAGING`, `INTERMEDIATE` or `MARTS` schemas.
3. **R3:** The scheduled pipeline builds production into `STAGING`, `INTERMEDIATE` and `MARTS`, as today.
4. **R4:** Building production by hand needs an explicit choice of the production environment; it is
   never the default.
5. **R5:** Every mart model declares, in the dbt project, read access for the Preset role in production.
   After every production build, including a full refresh, the Preset role can read every mart table
   without a manual grant.
6. **R6:** Development and CI schemas are not readable by the Preset role.
7. **R7:** A pull request's CI schemas remain after its CI run and are dropped when the pull request is
   merged or closed.
8. **R8:** Two developers building at the same time do not overwrite each other.
9. **R9:** Setup and docs explain which environment each command uses and how to clean up a
   development environment.

## Acceptance criteria

- **AC1:** Given a configured developer machine, when the developer runs the documented dbt build
  command, then new or replaced objects appear only in schemas carrying that developer's name, and the
  production marts' last-altered times do not change.
- **AC2:** Given the Dagster `full_pipeline` run, when it builds dbt, then the production `MARTS` tables
  are rebuilt and no developer schema is touched.
- **AC3:** Given a developer who runs the production build without choosing production explicitly, when
  the command runs, then it builds development, not production.
- **AC4:** Given a full refresh of `fct_sales` in production, when it finishes, then the Preset user can
  query the new table with no manual grant.
- **AC4b:** Given the compiled dbt project for production, when it is checked, then every mart model
  grants read access to the Preset role, and no development or CI build carries that grant. (The
  manual future grant is kept as a safety net, Q4, so AC4 alone cannot prove the declaration works.)
- **AC1b:** Given one changed staging model, when the developer runs the documented dev build, then
  only that model and its downstream models are built in the developer's schemas.
- **AC5:** Given a development or CI schema, when the Preset user tries to read it, then access is
  denied.
- **AC6:** Given an open pull request whose CI ran, when someone looks in the CI database, then that PR's
  schemas exist; when the PR is merged or closed, then they are gone.
- **AC7:** Given the docs, when a new developer follows them, then they can tell which command builds
  dev and which builds prod, and how to drop their dev schemas.

## Data contract changes

None for production: same database, schemas, tables, columns and grain. New per-developer schemas are
added outside the production contract.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Developers build into their own schemas; only the scheduled pipeline builds production by default | Accepted | A local build must not change what the dashboard shows |
| Preset read grants are declared in the dbt project and applied on every production build | Accepted | Grants made by hand are lost when objects or databases are recreated; the manual future grant stays as a safety net |
| CI schemas live for the life of the pull request | Accepted | Reviewers can inspect what a PR built; cleanup still happens |
| Development builds only changed models and reads the rest from production | Accepted | Cheapest option that still runs on real data; same mechanism as CI |

## Answers to open questions

Answered by the owner on 2026-10-15 (decision cards in the project thread).

- **Q1, where dev schemas live:** in the production database `RETAIL_PULSE`, one schema per developer
  and layer (for example `DBT_PHUCLH_MARTS`). The dbt role can already create schemas there.
- **Q2, how much a dev build processes:** only the changed models and their dependents; unchanged
  models are read from production.
- **Q3, how Preset grants are declared:** with dbt's built-in grants setting on the mart models, applied
  in production only.
- **Q4, the existing manual future grant:** kept as a safety net.

## Open questions

None.
