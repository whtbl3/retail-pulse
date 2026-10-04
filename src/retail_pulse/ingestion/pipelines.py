"""dlt: Postgres OLTP (schema retail) -> Snowflake RAW."""

from __future__ import annotations

import argparse

from dlt.sources.sql_database import sql_database

import dlt
from retail_pulse.oltp.db import engine

# Bảng có updated_at thay đổi -> incremental + merge theo khóa chính
INCREMENTAL: dict[str, list[str]] = {
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


def retail_source():
    source = sql_database(
        credentials=engine,  # dùng lại engine của oltp/db.py
        schema="retail",
        table_names=[*INCREMENTAL, *FULL_REFRESH],
        backend="sqlalchemy",
        reflection_level="full",  # giữ đúng precision/scale của NUMERIC(12,2)
    )
    for table, pk in INCREMENTAL.items():
        source.resources[table].apply_hints(
            primary_key=pk,
            write_disposition="merge",
            incremental=dlt.sources.incremental("updated_at"),
        )
    for table in FULL_REFRESH:
        source.resources[table].apply_hints(write_disposition="replace")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Postgres OLTP vào Snowflake RAW")
    parser.add_argument(
        "--full-refresh", action="store_true", help="Xóa bảng và state incremental, load lại từ đầu"
    )
    args = parser.parse_args()

    pipeline = dlt.pipeline(
        pipeline_name="retail_oltp_to_snowflake",
        destination="snowflake",
        dataset_name="raw",
        progress="log",
    )
    info = pipeline.run(retail_source(), refresh="drop_sources" if args.full_refresh else None)
    print(info)
    print(pipeline.last_trace.last_normalize_info)  # số dòng theo từng bảng


if __name__ == "__main__":
    main()
