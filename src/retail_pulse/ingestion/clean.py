"""Clean up everything dlt created: tables in Snowflake RAW + local state."""

from __future__ import annotations

import argparse
import shutil

import dlt

PIPELINE_NAME = "retail_oltp_to_snowflake"
DATASET_NAME = "raw"


def make_pipeline() -> dlt.Pipeline:
    # Must match pipeline_name / dataset_name in pipelines.py
    return dlt.pipeline(
        pipeline_name=PIPELINE_NAME, destination="snowflake", dataset_name=DATASET_NAME
    )


def clean_snowflake(pipeline: dlt.Pipeline) -> None:
    """Drop every table in RAW (including _dlt_*) and the RAW_STAGING schema.

    Keeps the RAW schema itself so role TRANSFORMER keeps its GRANTs.
    """
    with pipeline.sql_client() as client:
        db = client.database_name
        raw = f'"{db}"."{DATASET_NAME.upper()}"'
        staging = f'"{db}"."{DATASET_NAME.upper()}_STAGING"'

        tables = [row[1] for row in client.execute_sql(f"SHOW TABLES IN SCHEMA {raw}")]
        for name in tables:
            client.execute_sql(f'DROP TABLE IF EXISTS {raw}."{name}"')
        print(f"Snowflake: dropped {len(tables)} tables in {raw}")

        client.execute_sql(f"DROP SCHEMA IF EXISTS {staging} CASCADE")
        print(f"Snowflake: dropped schema {staging}")


def clean_local(pipeline: dlt.Pipeline) -> None:
    """Delete the pipeline's local state (incremental cursor, schema, temp files)."""
    path = pipeline.working_dir
    shutil.rmtree(path, ignore_errors=True)
    print(f"dlt: deleted local state {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up dlt and Snowflake RAW")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--local-only", action="store_true", help="Delete only the local dlt state")
    scope.add_argument("--snowflake-only", action="store_true", help="Drop only Snowflake tables")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    do_snowflake = not args.local_only
    do_local = not args.snowflake_only

    if not args.yes:
        targets = []
        if do_snowflake:
            targets.append("ALL tables in Snowflake RAW and RAW_STAGING")
        if do_local:
            targets.append("the local dlt state")
        if input(f"Will delete {' and '.join(targets)}. Type 'yes' to continue: ").strip() != "yes":
            raise SystemExit("Cancelled.")

    pipeline = make_pipeline()
    if do_snowflake:
        try:
            clean_snowflake(pipeline)
        except Exception as exc:  # RAW schema does not exist yet = already clean
            print(f"Snowflake: skipped ({exc})")
    if do_local:
        clean_local(pipeline)


if __name__ == "__main__":
    main()
