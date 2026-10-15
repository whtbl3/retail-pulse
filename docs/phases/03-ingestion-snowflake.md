# Phase 3: Ingestion PostgreSQL → Snowflake RAW (dlt)

Goal: move OLTP data to Snowflake. The first run loads everything, later runs load only new data.

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
```

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

Next: [Phase 4: Source change simulator](04-product-change-simulator.md).
