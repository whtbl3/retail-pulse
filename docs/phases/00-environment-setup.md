# Phase 0: Development environment

Goal: have every tool needed to run all later phases on a local machine.

| Component | Requirement |
|---|---|
| Operating system | Ubuntu or WSL2 |
| Python | 3.12 (pinned in `.python-version`) |
| Package manager | [uv](https://docs.astral.sh/uv/); `uv.lock` is the source of truth |
| Container | Docker + Docker Compose (runs PostgreSQL) |

## 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

*Why uv:* one command builds the right Python 3.12 environment with the exact version of each package (locked in `uv.lock`).
*If skipped:* every machine ends up with different package versions, and "works on my machine" bugs are very hard to reproduce.

## 2. Install packages and configure

```bash
make install               # = uv sync, also installs the dev group (ruff, pytest, sqlfluff, ...)
cp .env.example .env       # then edit PG_PASSWORD
```

*Why `.env`:* it keeps connection details out of the code. The file is already in `.gitignore`. Never commit it.
*If skipped:* `make up` stops right away with a message that `PG_USER` or `PG_PASSWORD` is missing.

`.env.example` lists every variable in the project, grouped by phase. For now you only need the PostgreSQL group. Fill in
the Snowflake group when you reach [phase 3](03-ingestion-snowflake.md), and the Preset password at phase 7.

The package list is in `pyproject.toml`, grouped by role: generator (`sqlalchemy`, `psycopg`, `faker`), ingestion
(`dlt[snowflake]`), transform (`dbt-core`, `dbt-snowflake`), orchestration (`dagster`, `dagster-dbt`, `dagster-dlt`),
quality (`great-expectations`), dev (`ruff`, `pytest`, `sqlfluff`, `pre-commit`, `pyrefly`).

## 3. Check the environment

```bash
make lint   # ruff check --fix + ruff format on src/
make test   # start Postgres, then run pytest (uses a temporary DB, dropped afterwards)
```

*Why:* you know the environment is right before going further, instead of hitting strange errors in a later phase.
Note that CI also checks the `tests/` folder (`ruff check src tests`), while `make lint` only runs on `src/`.

## Configuration and secrets

All credentials live outside git. For each one, the repo commits only a **template file** so you know what goes inside.
You create the real file yourself from the template.

| Real file (not committed) | Template (committed) | What it contains | Who reads it |
|---|---|---|---|
| `.env` | `.env.example` | PostgreSQL connection, Snowflake account, dbt key path and dev schema (`DBT_DEV_SCHEMA`), admin account (only for setup), Preset password | Python, Docker Compose, dbt, Great Expectations |
| `.dlt/secrets.toml` | `.dlt/secrets.toml.example` | Credentials of the `DLT_LOADER` user | dlt |
| `~/.dbt/profiles.yml` | `dbt/profiles.yml.example` | How dbt connects to Snowflake: targets `dev` (default) and `prod` (only references environment variables) | dbt |
| `.snowflake/*.p8` | no template | Private key of each user, created by `make snowflake-init` | dlt, dbt, CI |
| GitHub Secrets | see [phase 9](09-dataops-ci.md) | `SNOWFLAKE_ACCOUNT`, `CI_PRIVATE_KEY` | CI |

*Why split template and real file:* readers see at once what needs configuring, and no secret reaches git.
*If you commit a real file:* this repo is public, so anyone can read it. A leaked key or password must be rotated at once.
Deleting the commit afterwards does not take it back.

Quick check before committing: `git status` must not list `.env`, `.dlt/secrets.toml` or any `.p8` file.

## Folder structure

```text
.
├── Makefile                  # common commands: make help
├── README.md                 # problem, data model, architecture
├── pyproject.toml, uv.lock   # packages and versions
├── .env.example              # config template: PostgreSQL, Snowflake, Preset (real file is .env, not committed)
├── .github/workflows/        # CI: ci.yml, manifest.yml
├── assets/diagrams/          # images used in the docs
├── .dlt/secrets.toml.example # dlt credential template (real file is .dlt/secrets.toml, not committed)
├── dbt/                      # dbt project: models, tests, macros, ci/profiles.yml, profiles.yml.example
├── docs/
│   ├── README.md             # overview and phase roadmap
│   ├── Project-Spec.md       # the project's reference specification
│   ├── phases/               # how to run each phase
│   └── design/               # detailed design of each component
├── infras/
│   ├── docker-compose.yml
│   ├── postgres/init/01_schema.sql
│   └── snowflake/init.sql
├── src/retail_pulse/
│   ├── oltp/                 # SQLAlchemy engine and ORM models
│   ├── generator/            # seed.py, stream.py, common.py
│   ├── ingestion/            # dlt pipelines, RAW cleanup, Snowflake setup
│   ├── orchestration/        # Dagster: dlt and dbt assets, jobs, schedules
│   └── quality/              # Great Expectations checks on RAW
└── tests/                    # pytest
```

## Further reading

- [uv: working on projects](https://docs.astral.sh/uv/concepts/projects/layout/) and
  [`uv sync`](https://docs.astral.sh/uv/concepts/projects/sync/): why `uv.lock` exists and how to sync the environment.
- [Ruff](https://docs.astral.sh/ruff/) (lint and format) and [pytest](https://docs.pytest.org/en/stable/).

Next: [Phase 1: PostgreSQL OLTP](01-oltp-database.md).
