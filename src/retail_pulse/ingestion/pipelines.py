"""dlt: Postgres OLTP (schema retail) -> Snowflake RAW."""

from __future__ import annotations

import argparse

from dlt.sources.sql_database import sql_database

import dlt
from retail_pulse.oltp.db import engine

# Bảng có updated_at -> incremental append (không merge, rẻ hơn trên Snowflake).
# Mỗi lần một dòng đổi là một dòng mới trong RAW; dbt dựng SCD2 từ các dòng đó.
APPEND: dict[str, list[str]] = {
    "sales_transaction": ["transaction_id"],
    "sales_transaction_item": ["transaction_id", "line_number"],
    "product": ["id"],  # nguồn cho dim_product SCD2
    "employee": ["id"],  # nguồn cho dim_employee SCD2
}
# Bảng nhỏ -> ghi đè toàn bộ mỗi lần chạy
FULL_REFRESH: list[str] = [
    "store",
    "category",
    "brand",
    "payment_method",
    "promotion",
    "promotion_product",
]


def retail_pipeline(progress: str | None = None) -> dlt.Pipeline:
    """Một nơi duy nhất định nghĩa pipeline, dùng chung cho CLI và Dagster"""
    return dlt.pipeline(
        pipeline_name="retail_oltp_to_snowflake",
        destination="snowflake",
        dataset_name="raw",
        progress=progress,
    )


def retail_source():
    source = sql_database(
        credentials=engine,  # dùng lại engine của oltp/db.py
        schema="retail",
        table_names=[*APPEND, *FULL_REFRESH],
        backend="sqlalchemy",
        reflection_level="full",  # giữ đúng precision/scale của NUMERIC(12,2)
        defer_table_reflect=True,  # chỉ đọc cấu trúc bảng lúc chạy, để import không cần Postgres
    )
    for table, pk in APPEND.items():
        source.resources[table].apply_hints(
            primary_key=pk,  # chỉ để dlt bỏ dòng trùng ở mốc con trỏ, không merge
            write_disposition="append",
            incremental=dlt.sources.incremental("updated_at"),
        )
    for table in FULL_REFRESH:
        source.resources[table].apply_hints(write_disposition="replace")
    return source


def main() -> None:
    argparse.ArgumentParser(description="Load Postgres OLTP vào Snowflake RAW").parse_args()

    pipeline = retail_pipeline(progress="log")
    info = pipeline.run(retail_source())
    print(info)
    print(pipeline.last_trace.last_normalize_info)


if __name__ == "__main__":
    main()
