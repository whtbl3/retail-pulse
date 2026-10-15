# RetailPulse documentation

This page is the starting point: what each phase does and which document to read.
The problem, data modeling and overall architecture are in the [root README](../README.md).
The canonical specification (scope, data contracts, acceptance criteria, decision log) is
[Project-Spec.md](Project-Spec.md); when another document disagrees with the spec, the spec wins.

## End-to-end flow

```text
seed.py / stream.py ──► PostgreSQL (OLTP, 3NF) ──dlt──► Snowflake RAW ──dbt──► staging ► marts (SCD2) ──► Preset
                                     Dagster orchestrates ingest + transform
```

## Phase roadmap

| Phase | Content | Document |
|---|---|---|
| 0 | Environment: uv, Docker, repo layout | [phases/00-environment-setup.md](phases/00-environment-setup.md) |
| 1 | PostgreSQL OLTP: schema, ORM, Docker Compose | [phases/01-oltp-database.md](phases/01-oltp-database.md) |
| 2 | Historical data seed (`seed.py`) | [phases/02-historical-seed.md](phases/02-historical-seed.md) |
| 3 | dlt full + incremental ingestion into Snowflake RAW | [phases/03-ingestion-snowflake.md](phases/03-ingestion-snowflake.md) |
| 4 | Product price change simulation (`stream.py`) | [phases/04-product-change-simulator.md](phases/04-product-change-simulator.md) |
| 5 | dbt: staging, SCD2, star schema | [phases/05-dbt.md](phases/05-dbt.md) |
| 6 | Dagster orchestration | [phases/06-dagster.md](phases/06-dagster.md) |
| 7 | Preset dashboards | [phases/07-preset.md](phases/07-preset.md) |
| 8 | Great Expectations: RAW quality checks | [phases/08-great-expectations.md](phases/08-great-expectations.md) |
| 9 | DataOps: GitHub Actions, slim CI for dbt | [phases/09-dataops-ci.md](phases/09-dataops-ci.md) |
| 10 | Operations: always-on Dagster in Docker, retries, RAW freshness, Slack alerts | [phases/10-operations.md](phases/10-operations.md), [runbook.md](runbook.md) |

## Detailed design by component

| Component | Document | Code | Test |
|---|---|---|---|
| Data generator (seed + stream) | [design/data-generator.md](design/data-generator.md) | `src/retail_pulse/generator/` | `tests/test_seed.py`, `tests/test_stream.py` |
| Operational data modeling (OLTP: conceptual, logical, physical) | [design/operational-data-modeling.md](design/operational-data-modeling.md) | `infras/postgres/init/01_schema.sql`, `src/retail_pulse/oltp/` | — |
| Analytical data modeling (Kimball: process, grain, dimension, fact) | [design/analytical-data-modeling.md](design/analytical-data-modeling.md) | dbt (phase 5) | — |

## Workflow

| Topic | Document |
|---|---|
| Claude Code: `CLAUDE.md`, permissions and hooks in `.claude/` | [claude-code.md](claude-code.md) |
| Code review: `REVIEW.md`, `spec-reviewer` subagent | [code-review.md](code-review.md) |
| Spec-driven development: Intent issue, `specs/`, `/new-feature` skill, trying Spec Kit | [spec-driven-development.md](spec-driven-development.md), [specs/README.md](../specs/README.md) |

## Quick start

Up to Postgres (needs only Docker, no Snowflake yet):
```bash
make install              # install dependencies (uv sync)
cp .env.example .env      # then edit PG_PASSWORD
make up                   # start PostgreSQL
make seed                 # load ~100k historical transactions
make test                 # run all tests
```

On to Snowflake, dbt and Dagster (needs the setup from [phase 3](phases/03-ingestion-snowflake.md) and [phase 5](phases/05-dbt.md)):
```bash
make snowflake-init       # once: create warehouse, database, role, user
make ingest               # load Postgres into Snowflake RAW
make dbt-deps && make dbt-build   # build staging through marts and run tests
make dagster              # open the Dagster UI to orchestrate the whole chain
```
`make help` lists every command.

> **Careful:** `make seed`, `make reseed` and `make db-reset` all **delete RAW on Snowflake** before running. RAW is the
> only place that keeps the SCD2 history of `product` and `employee`, so deleting it loses that history. Details in [phase 2](phases/02-historical-seed.md).

## Documentation conventions

- `docs/phases/NN-*.md`: how to **run and verify** a phase: what to do, which commands, expected results.
- `docs/design/<component>.md`: **why it is designed this way** and how it is implemented, for people changing the code.
- Every manual step states **why you do it** and **what happens if you skip it**. New concepts get a "Further reading" section with links checked to be live.
- Write briefly, in the order the reader needs to act. Everything is in English.
- When adding a phase: create the file in `phases/` and add a row to the table above in the same change.
