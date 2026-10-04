"""Dọn sạch dữ liệu do dlt tạo ra: bảng trên Snowflake RAW + state cục bộ."""

from __future__ import annotations

import argparse
import shutil

import dlt

PIPELINE_NAME = "retail_oltp_to_snowflake"
DATASET_NAME = "raw"


def make_pipeline() -> dlt.Pipeline:
    # Phải khớp pipeline_name / dataset_name trong pipelines.py
    return dlt.pipeline(
        pipeline_name=PIPELINE_NAME, destination="snowflake", dataset_name=DATASET_NAME
    )


def clean_snowflake(pipeline: dlt.Pipeline) -> None:
    """Xoá mọi bảng trong RAW (gồm _dlt_*) và schema RAW_STAGING.

    Giữ nguyên schema RAW để không mất GRANT của role TRANSFORMER.
    """
    with pipeline.sql_client() as client:
        db = client.database_name
        raw = f'"{db}"."{DATASET_NAME.upper()}"'
        staging = f'"{db}"."{DATASET_NAME.upper()}_STAGING"'

        tables = [row[1] for row in client.execute_sql(f"SHOW TABLES IN SCHEMA {raw}")]
        for name in tables:
            client.execute_sql(f'DROP TABLE IF EXISTS {raw}."{name}"')
        print(f"Snowflake: đã xoá {len(tables)} bảng trong {raw}")

        client.execute_sql(f"DROP SCHEMA IF EXISTS {staging} CASCADE")
        print(f"Snowflake: đã xoá schema {staging}")


def clean_local(pipeline: dlt.Pipeline) -> None:
    """Xoá state cục bộ (incremental cursor, schema, file tạm) của pipeline."""
    path = pipeline.working_dir
    shutil.rmtree(path, ignore_errors=True)
    print(f"dlt: đã xoá state cục bộ {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dọn dlt và Snowflake RAW")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--local-only", action="store_true", help="Chỉ xoá state cục bộ của dlt")
    scope.add_argument("--snowflake-only", action="store_true", help="Chỉ xoá bảng trên Snowflake")
    parser.add_argument("-y", "--yes", action="store_true", help="Bỏ qua bước xác nhận")
    args = parser.parse_args()

    do_snowflake = not args.local_only
    do_local = not args.snowflake_only

    if not args.yes:
        targets = []
        if do_snowflake:
            targets.append("TOÀN BỘ bảng trong Snowflake RAW và RAW_STAGING")
        if do_local:
            targets.append("state cục bộ của dlt")
        if input(f"Sẽ xoá {' và '.join(targets)}. Gõ 'yes' để tiếp tục: ").strip() != "yes":
            raise SystemExit("Đã huỷ.")

    pipeline = make_pipeline()
    if do_snowflake:
        try:
            clean_snowflake(pipeline)
        except Exception as exc:  # schema RAW chưa tồn tại = đã sạch
            print(f"Snowflake: bỏ qua ({exc})")
    if do_local:
        clean_local(pipeline)


if __name__ == "__main__":
    main()
