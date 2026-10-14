# Phase 1: PostgreSQL OLTP

Goal: build a 3NF source database that simulates a retail POS system.
Why it is designed this way (conceptual → logical → physical): [Operational data modeling](../design/operational-data-modeling.md).

## Components

| File | Role |
|---|---|
| `infras/docker-compose.yml` | `postgres:16` container |
| `infras/postgres/init/01_schema.sql` | DDL: `retail` schema, constraints, indexes, `updated_at` trigger |
| `src/retail_pulse/oltp/db.py` | Reads the `PG_*` settings from `.env`, creates `engine` and `SessionLocal` |
| `src/retail_pulse/oltp/models.py` | ORM models that match the DDL |

`docker-compose.yml` already sets `wal_level=logical`, reserved for CDC later. It is not used yet because CDC is out of scope.

## Conventions for every table

| Convention | Why | If skipped |
|---|---|---|
| Primary key `BIGINT GENERATED ALWAYS AS IDENTITY` | Auto-increment key; the application never sets it | Duplicate keys or wrong hand-set keys |
| `created_at` and `updated_at` (`TIMESTAMPTZ`), a trigger updates `updated_at` on UPDATE | `updated_at` is the cursor dlt uses for incremental loads | If an UPDATE does not change `updated_at`, dlt misses the change and RAW drifts from the source |
| Money uses `NUMERIC(12, 2)` with `CHECK (>= 0)` | Exact decimals; blocks negative money at the source | `float` accumulates rounding errors; negative values leak into analytics |

## Run

```bash
make up        # start Postgres, wait for the healthcheck
make psql      # open psql on retail_oltp
make down      # stop the container, keep the data
make db-reset  # recreate the DB from 01_schema.sql
```

`01_schema.sql` only runs when the volume is empty, so after editing the DDL you must run `make db-reset`.
**`make db-reset` also deletes RAW on Snowflake and the dlt state**, not just the Postgres volume. RAW holds the SCD2
history, so only run it if you accept losing that history.

## Check

```sql
\dt retail.*                       -- 10 tables
SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_%_updated_at';
```

## Further reading

- [PostgreSQL: trigger functions in PL/pgSQL](https://www.postgresql.org/docs/16/plpgsql-trigger.html): how the `updated_at` trigger works.
- [PostgreSQL: numeric types](https://www.postgresql.org/docs/16/datatype-numeric.html): why money uses `NUMERIC`.
- [Docker Compose](https://docs.docker.com/compose/).

Next: [Phase 2: Historical data seed](02-historical-seed.md).
