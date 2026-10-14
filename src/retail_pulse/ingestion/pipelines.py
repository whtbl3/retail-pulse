"""dlt: Postgres OLTP (schema retail) -> Snowflake RAW."""

from __future__ import annotations

import argparse

import dlt
from dlt.sources.sql_database import sql_database

from retail_pulse.oltp.db import engine

# Tables with updated_at -> incremental append (no merge, cheaper on Snowflake).
# Every change to a row becomes a new row in RAW; dbt builds SCD2 from those rows.
APPEND: dict[str, list[str]] = {
    "sales_transaction": ["transaction_id"],
    "sales_transaction_item": ["transaction_id", "line_number"],
    "product": ["id"],  # source of dim_product SCD2
    "employee": ["id"],  # source of dim_employee SCD2
}
# Small tables -> fully replaced on every run
FULL_REFRESH: list[str] = [
    "store",
    "category",
    "brand",
    "payment_method",
    "promotion",
    "promotion_product",
]


def retail_pipeline(progress: str | None = None) -> dlt.Pipeline:
    """The single place that defines the pipeline, shared by the CLI and Dagster"""
    return dlt.pipeline(
        pipeline_name="retail_oltp_to_snowflake",
        destination="snowflake",
        dataset_name="raw",
        progress=progress,
    )


def retail_source():
    source = sql_database(
        credentials=engine,  # reuse the engine from oltp/db.py
        schema="retail",
        table_names=[*APPEND, *FULL_REFRESH],
        backend="sqlalchemy",
        reflection_level="full",  # keep the exact precision/scale of NUMERIC(12,2)
        defer_table_reflect=True,  # reflect tables only at run time, so importing needs no Postgres
    )
    for table, pk in APPEND.items():
        source.resources[table].apply_hints(
            primary_key=pk,  # only lets dlt drop duplicates at the cursor boundary, no merge
            write_disposition="append",
            incremental=dlt.sources.incremental("updated_at"),
        )
    for table in FULL_REFRESH:
        source.resources[table].apply_hints(write_disposition="replace")
    return source


def main() -> None:
    argparse.ArgumentParser(description="Load Postgres OLTP into Snowflake RAW").parse_args()

    pipeline = retail_pipeline(progress="log")
    info = pipeline.run(retail_source())
    print(info)
    print(pipeline.last_trace.last_normalize_info)


if __name__ == "__main__":
    main()
