# Phase 3: Ingestion PostgreSQL → Snowflake RAW (dlt)

Goal: move OLTP data to Snowflake. The first run loads everything, later runs load only new data.

## Why it is needed

Postgres is built to record sales (OLTP), not to answer analytics queries, and it only keeps the current state of
each row. This phase copies the data into Snowflake, a warehouse built for analytics, as an
untouched `RAW` layer that dbt transforms in phase 5 (ELT: load first, transform in the warehouse). Because changed
`product` and `employee` rows are appended as new rows, RAW becomes the only place that keeps their history; dbt builds
SCD2 from it. Loading only new rows (incremental) keeps each run small and cheap. It also sets up dedicated Snowflake
users and roles, so a bug in dlt or dbt cannot delete data it should not touch.

## Concepts

| Term | Meaning here |
|---|---|
| dlt pipeline | The Python object that reads from Postgres and loads into Snowflake. `retail_pipeline()` in `ingestion/pipelines.py` is the only definition, used by `make ingest` and Dagster |
| Resource | One table in the dlt source. Each gets its own load method (append or replace) |
| Incremental load | Each run loads only rows newer than the previous run, instead of the whole table |
| Cursor | The column that tells dlt what is new: `updated_at`. dlt stores the last value it loaded (its state) in `~/.dlt/pipelines` |
| Append-only | New and changed rows are added as new rows in RAW; nothing is updated or deleted. Used for the four tables with `updated_at` |
| Replace | The table in RAW is overwritten on every run. Used for the six small reference tables |
| Role and service user | `LOADER` / `DLT_LOADER` for dlt, `TRANSFORMER` / `DBT_TRANSFORMER` for dbt, each with only the privileges it needs |
| Key-pair auth | Login with a private key kept on your machine (`.snowflake/*.p8`); Snowflake stores only the public key. No password to leak |

| Table | Load method | Key / cursor |
|---|---|---|
| `sales_transaction`, `sales_transaction_item`, `product`, `employee` | incremental, **append** | `updated_at` |
| `store`, `category`, `brand`, `payment_method`, `promotion`, `promotion_product` | replace (overwrite) | whole table |

> **Append, not merge.** A changed row (`product`, `employee`) becomes a **new** row in RAW: same `id`, new
> `updated_at`. So RAW keeps every version, and dbt builds SCD2 from it. Two limits: each `stream.py` cycle must be
> ingested before the next cycle (the cursor only sees the final state), and the source has no DELETE (the cursor
> cannot see deleted rows).

> **Careful: RAW is the only place that keeps the history of `product` and `employee`.** That is why `ingest` has no
> `--full-refresh` flag. Starting over with `uv run clean-ingest` (asks for confirmation) or `make clean-raw` (does not
> ask) and then `make ingest` **deletes all history**. Only do it if you accept the loss.

Detailed contract: [Project-Spec, section 9](../Project-Spec.md#9-ingestion-specification).
Code: `src/retail_pulse/ingestion/pipelines.py` (pipeline), `clean.py` (RAW cleanup).

## 1. Set up Snowflake

dlt and dbt should not run with an admin account: a small bug in the code could delete all raw data. This step builds
the "room" (database, warehouse) and the "keys" (roles, users) with just enough privileges, using one SQL file
([`infras/snowflake/init.sql`](../../infras/snowflake/init.sql)) that is safe to run any number of times.

> **Shortcut:** `make setup` runs this step and step 2 for you. It asks for the account identifier and the
> `ACCOUNTADMIN` login (the password is passed to `snowflake-init` in memory and never saved), fixes the
> placeholders in `.env`, and writes `.dlt/secrets.toml` with `private_key_path`. The sections below explain
> what it does.

### Prerequisites

You need a user with the `ACCOUNTADMIN` role and three variables in `.env` (see `.env.example`): `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_ADMIN_USER`, `SNOWFLAKE_ADMIN_PASSWORD`. If `SNOWFLAKE_ACCOUNT` is missing, the command uses `host` from `.dlt/secrets.toml`.

*Why `ACCOUNTADMIN`:* only this role can create resource monitors, roles and users.
*If a variable is missing:* the command stops with a "Missing ..." message and creates nothing on Snowflake.

### Run

```bash
make snowflake-init-dry   # preview, does not connect to Snowflake
make snowflake-init       # real run
```

The command splits the SQL file into statements, creates a key pair for each user if none exists (`.snowflake/<name>.p8`
and `.pub`), attaches the public key to the user, then runs the statements in order. Rerunning is safe because every
statement is `IF NOT EXISTS` or `GRANT`. Existing objects are not changed, as long as you keep the key files.

### What gets created

| Object | Name | What it is for | If missing |
|---|---|---|---|
| Resource monitor | `RETAIL_RM` | Cap of 10 credits per month, warning at 80%, auto suspend at 100% | One bad query could burn all credits |
| Warehouse | `RETAIL_WH` (XSMALL) | Compute for every query; suspends after 60 seconds idle, resumes when needed | Nowhere to run queries; without auto suspend it costs money while idle |
| Database | `RETAIL_PULSE` | Holds all project data | Nowhere to store data |
| Schema | `RAW` | The only place dlt writes to | dlt has nowhere to load |
| Schema | `STAGING`, `INTERMEDIATE`, `MARTS` | dbt layers, owned by the `TRANSFORMER` role | dbt can create them on the first build; created early so CI can be granted read access |
| Role | `LOADER`, `TRANSFORMER` | Privileges by task (table below) | Everything would share one high-privilege role |
| User | `DLT_LOADER`, `DBT_TRANSFORMER` | Accounts for dlt and dbt, type SERVICE, key pair login | The two tools have no separate identity to grant privileges to |

The CI part (`RETAIL_PULSE_CI`, `CI_RUNNER`, `GITHUB_CI`) is at the end of the file and explained in [phase 9](09-dataops-ci.md).

### Who can do what

| Role | `RAW` | `STAGING`, `INTERMEDIATE`, `MARTS` | Notes |
|---|---|---|---|
| `LOADER` (dlt) | Read and write | No access | Can create schemas, because dlt may create a temporary `RAW_STAGING` schema during loads |
| `TRANSFORMER` (dbt) | **Read only** | Read and write (owner) | Cannot change or delete raw data |

*Why dbt can only read `RAW`:* RAW is the only place that keeps the SCD2 history of `product` and `employee`. If dbt
could write there, one buggy model could destroy history that cannot be recovered.

### How the access rules are wired

The two tables above show the result. Four mechanisms in `init.sql` produce it, and each one fixes a problem that
would otherwise appear later, often only on the second or third run.

```text
ACCOUNTADMIN
   └── SYSADMIN
         ├── LOADER ──────▶ USAGE on RETAIL_WH, ALL on schema RAW      ◀── granted to user DLT_LOADER
         └── TRANSFORMER ─▶ USAGE on RETAIL_WH, SELECT on RAW tables,  ◀── granted to user DBT_TRANSFORMER
                            owner of STAGING, INTERMEDIATE, MARTS
```

**1. Role hierarchy: the new roles sit under `SYSADMIN`.**

```sql
GRANT ROLE LOADER TO ROLE SYSADMIN;
GRANT ROLE TRANSFORMER TO ROLE SYSADMIN;
```

Granting a role to another role makes the second one inherit every privilege of the first. `SYSADMIN` is the
built-in role meant to manage databases and warehouses, and `ACCOUNTADMIN` already sits above it, so both now inherit
everything `LOADER` and `TRANSFORMER` can do, including the objects they own. Snowflake recommends attaching every
custom role to `SYSADMIN` this way: when a role sits outside that tree, administrators cannot manage the
tables it owns, for example to inspect or drop a table dlt created. The arrow only goes up: `LOADER` and `TRANSFORMER`
gain nothing from `SYSADMIN`, so they stay least-privilege. The same pattern is used for `CI_RUNNER` in section 5.

**2. Users get roles; privileges belong to roles.**

```sql
CREATE USER IF NOT EXISTS DLT_LOADER TYPE = SERVICE DEFAULT_ROLE = LOADER DEFAULT_WAREHOUSE = RETAIL_WH;
GRANT ROLE LOADER TO USER DLT_LOADER;
```

Snowflake never grants a privilege straight to a user here. The chain is always user → role → privilege: `DLT_LOADER`
holds the role `LOADER`, and `LOADER` holds the privileges on `RETAIL_WH` and `RAW`. To change what dlt may do, you
change the role, not the user. `DEFAULT_ROLE` and `DEFAULT_WAREHOUSE` only choose the role and warehouse a session
starts with, so dlt and dbt do not have to run `USE ROLE` or `USE WAREHOUSE` after connecting. They do **not** grant
anything: Snowflake's docs state that a default role must still be granted with `GRANT ROLE`, which is why every
`CREATE USER` is followed by a `GRANT ROLE ... TO USER`. Without that line the default role would name a role the user
does not hold.

**3. Future grants: tables dlt creates later are readable by dbt automatically.**

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA RETAIL_PULSE.RAW TO ROLE TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA RETAIL_PULSE.RAW TO ROLE TRANSFORMER;
```

dlt (role `LOADER`) creates the RAW tables, so `LOADER` owns them and `TRANSFORMER` has no access by default. `ON ALL
TABLES` covers only tables that exist when the statement runs; on a fresh account RAW is still empty, so it grants
nothing. `ON FUTURE TABLES` covers every table created in RAW afterwards: when dlt loads a new table, Snowflake
gives `TRANSFORMER` `SELECT` on it at creation. Without the future grant, the first ingest that adds a table would make
the next `dbt build` fail with an "insufficient privileges" or "does not exist or not authorized" error until someone
granted access by hand. Keep both lines: `ALL` covers tables created before the future grant existed (for example, an account set up with an
older version of the script), `FUTURE` covers new ones.
Two details: a schema-level future grant like this one overrides any database-level future grant, and only a role
with `MANAGE GRANTS` (here `ACCOUNTADMIN`) can create it. `CI_RUNNER` gets the same pair on every schema it reads.

**4. Ownership: the dbt schemas are created as `TRANSFORMER`.**

```sql
USE ROLE TRANSFORMER;
CREATE SCHEMA IF NOT EXISTS RETAIL_PULSE.STAGING;
CREATE SCHEMA IF NOT EXISTS RETAIL_PULSE.INTERMEDIATE;
CREATE SCHEMA IF NOT EXISTS RETAIL_PULSE.MARTS;
USE ROLE ACCOUNTADMIN;
```

In Snowflake the role that is active when an object is created becomes its owner, and the owner has full control
of it: create, replace and drop tables and views inside, and grant access to others. The script runs as
`ACCOUNTADMIN`, so without the switch the three schemas would belong to `ACCOUNTADMIN`, and dbt would get
"insufficient privileges" when it tries to create its models there. Switching to `TRANSFORMER` first makes dbt the
owner of its own layers with no extra grants. The switch is possible because of mechanism 1: `TRANSFORMER` sits
under `SYSADMIN` and `ACCOUNTADMIN`, so the admin user running the script can take it on, and `TRANSFORMER` already
has `CREATE SCHEMA` on the database. The script switches back to `ACCOUNTADMIN` right after, because section 5
creates a warehouse, a role and a user, which `TRANSFORMER` is not allowed to do.

Compare with `RAW`: it is created as `ACCOUNTADMIN` and `LOADER` only gets `ALL` on it, not ownership. dlt can create
and fill tables there, but cannot drop the schema or change who else has access to it.

### Why key pairs, not passwords

The private key stays on your machine, and Snowflake only keeps the public key. There is no password to leak or
rotate, and SERVICE users cannot log in through the web UI. Further reading:
[Snowflake: key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth).

### Check

```sql
USE ROLE ACCOUNTADMIN;
DESC USER DLT_LOADER;                  -- the RSA_PUBLIC_KEY_FP column must look like SHA256:...
SHOW GRANTS TO ROLE LOADER;            -- shows ALL privileges on the RAW schema
SHOW SCHEMAS IN DATABASE RETAIL_PULSE; -- shows RAW, STAGING, INTERMEDIATE, MARTS
SHOW GRANTS OF ROLE TRANSFORMER;       -- granted to role SYSADMIN and to user DBT_TRANSFORMER
SHOW FUTURE GRANTS IN SCHEMA RETAIL_PULSE.RAW; -- SELECT on TABLE to TRANSFORMER and CI_RUNNER
```

The `owner` column of `SHOW SCHEMAS` must read `TRANSFORMER` for `STAGING`, `INTERMEDIATE` and `MARTS`.

*If `RSA_PUBLIC_KEY_FP` is empty:* the public key is not attached to the user, and dlt will not be able to log in.

### Redo or rotate keys

To create a new key for a user: delete **both** the `.p8` and `.pub` files of that user in `.snowflake/`, rerun
`make snowflake-init`, then update the matching `private_key` (`.dlt/secrets.toml` for dlt, the `.p8` file that
`DBT_PRIVATE_KEY_PATH` points to for dbt). The rerun attaches the new public key, so the old key stops working at once.

### Common errors

| Symptom | Usual cause | Fix |
|---|---|---|
| "Missing SNOWFLAKE_ADMIN_USER..." | Environment variable not set | Fill it in `.env` or `export` it |
| Error says role `ACCOUNTADMIN` is not granted to the user | The admin user does not have this role | Use a user that has `ACCOUNTADMIN` |
| dlt or dbt reports an authentication error (often `JWT token is invalid`) | The private key does not match the attached public key, or the key path is wrong | Check `RSA_PUBLIC_KEY_FP`; if you recreated the key, update both places |

## 2. Configure dlt credentials

```bash
cp .dlt/secrets.toml.example .dlt/secrets.toml   # real file, do NOT commit
```
Then fill in `host` (the Snowflake account) and `private_key` (the `DLT_LOADER` key). The other fields
(`database = "RETAIL_PULSE"`, `username = "DLT_LOADER"`, `warehouse = "RETAIL_WH"`, `role = "LOADER"`) are already correct in the template.

*About the `private_key` format:* dlt accepts the key as a base64 string, or use `private_key_path` pointing to a PEM file. See
the [dlt docs for Snowflake](https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake).
*If skipped:* `make ingest` stops with an error about missing credentials for the Snowflake destination.

## 3. First load

```bash
make ingest
```

There is no incremental cursor yet, so dlt loads everything. It succeeded when the log ends with
`... is LOADED and contains no failed jobs` and a list of row counts. For example, the first load of the default seed:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `sales_transaction` | 100,339 | `product` | 500 |
| `sales_transaction_item` | 286,797 | `employee` | 80 |
| `promotion_product` | 483 | `brand` | 30 |
| `category` | 10 | `store` | 10 |
| `payment_method` | 4 | `promotion` | 40 |

## 4. Check on Snowflake

```sql
USE ROLE ACCOUNTADMIN;
SHOW SCHEMAS IN DATABASE RETAIL_PULSE;     -- shows RAW (and RAW_STAGING if dlt needs it)

SELECT TABLE_NAME, ROW_COUNT
FROM RETAIL_PULSE.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'RAW'
ORDER BY TABLE_NAME;
```

## 5. Later runs: incremental

```bash
make ingest          # only fetches rows with updated_at newer than the last run, appends them
```

Dagster runs the same pipeline ([phase 6](06-dagster.md)) and shares the dlt state in `~/.dlt/pipelines`.

## Further reading

- [dlt: incremental loading](https://dlthub.com/docs/general-usage/incremental-loading): how the `updated_at` cursor works.
- [dlt: `sql_database` source](https://dlthub.com/docs/dlt-ecosystem/verified-sources/sql_database): how tables are read from PostgreSQL.
- [Snowflake: key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth).
- [Snowflake: access control overview](https://docs.snowflake.com/en/user-guide/security-access-control-overview): roles, role hierarchy, ownership.
- [Snowflake: `GRANT <privileges>`](https://docs.snowflake.com/en/sql-reference/sql/grant-privilege): `ON ALL` and `ON FUTURE` grants.
- [Snowflake: `CREATE USER`](https://docs.snowflake.com/en/sql-reference/sql/create-user): `DEFAULT_ROLE` does not grant the role.

Next: [Phase 4: Source change simulator](04-product-change-simulator.md).
