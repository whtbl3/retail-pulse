---
name: retail-pulse
description: Use when working on the RetailPulse data engineering project (PostgreSQL source, dlt ingestion, dbt on Snowflake, Dagster, Preset). Covers project scope, finalized decisions, and conventions for seed.py, stream.py, and dbt snapshots.
---

# retail-pulse

## When to use
- Editing code under `src/retail_pulse` (`generator`, `ingestion`, `oltp`)
- Writing dbt models, snapshots, or Dagster assets for this project

## Instructions
1. Respect finalized decisions: PostgreSQL source, dlt for ingestion, dbt snapshots for SCD2, Docker Compose only.
2. `seed.py` generates batch reference data and historical transactions.
3. `stream.py` only simulates small, realistic product changes in the source system for the current phase.
4. Never implement SCD logic in Python generators; history tracking belongs in dbt snapshots.
5. Do not expand stream scope to new orders or order status changes unless the schema and spec are explicitly updated.
6. Current source scope excludes `customer` and does not include order status `pending`.
