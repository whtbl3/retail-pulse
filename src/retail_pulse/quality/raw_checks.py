"""Great Expectations: check RAW data quality before dbt runs.

Covers only what dbt tests do not: dbt tests check staging/marts, this stops bad data at RAW.
Reads as the dbt user (role TRANSFORMER, SELECT only on RAW). Data is pulled into pandas, so no
snowflake-sqlalchemy is needed (installing it would downgrade the project's sqlalchemy).
"""

import os
import sys

import great_expectations as gx
import great_expectations.expectations as gxe
import pandas as pd
import snowflake.connector

# ponytail: pulls whole tables into RAM (fine for a few hundred thousand rows); at tens of millions
# switch to a GX SQL datasource (push the checks down to Snowflake) or sample.
TABLES: dict[str, tuple[str, list]] = {
    "sales_transaction": (
        "transaction_id, store_id, employee_id, payment_method_id, transaction_ts, "
        "status, updated_at",
        [
            gxe.ExpectTableRowCountToBeBetween(min_value=1),
            *[
                gxe.ExpectColumnValuesToNotBeNull(column=c)
                for c in [
                    "transaction_id",
                    "store_id",
                    "employee_id",
                    "payment_method_id",
                    "transaction_ts",
                    "updated_at",
                ]
            ],
            gxe.ExpectColumnValuesToBeInSet(
                column="status", value_set=["completed", "cancelled", "returned"]
            ),
        ],
    ),
    "sales_transaction_item": (
        "transaction_id, line_number, product_id, quantity::float AS quantity, "
        "regular_price::float AS regular_price, coupon_amount::float AS coupon_amount",
        [
            gxe.ExpectTableRowCountToBeBetween(min_value=1),
            *[
                gxe.ExpectColumnValuesToNotBeNull(column=c)
                for c in [
                    "transaction_id",
                    "line_number",
                    "product_id",
                    "quantity",
                    "regular_price",
                ]
            ],
            gxe.ExpectColumnValuesToBeBetween(column="quantity", min_value=1),
            gxe.ExpectColumnValuesToBeBetween(column="regular_price", min_value=0),
            gxe.ExpectColumnValuesToBeBetween(column="coupon_amount", min_value=0),
        ],
    ),
    "product": (
        "id, product_sku, unit_price::float AS unit_price, unit_cost::float AS unit_cost, "
        "updated_at",
        [
            gxe.ExpectTableRowCountToBeBetween(min_value=1),
            *[
                gxe.ExpectColumnValuesToNotBeNull(column=c)
                for c in ["id", "product_sku", "unit_price", "unit_cost", "updated_at"]
            ],
            gxe.ExpectColumnValuesToBeBetween(column="unit_price", min_value=0),
            gxe.ExpectColumnValuesToBeBetween(column="unit_cost", min_value=0),
        ],
    ),
    "employee": (
        "id, store_id, salary::float AS salary, updated_at",
        [
            gxe.ExpectTableRowCountToBeBetween(min_value=1),
            *[
                gxe.ExpectColumnValuesToNotBeNull(column=c)
                for c in ["id", "store_id", "updated_at"]
            ],
            gxe.ExpectColumnValuesToBeBetween(column="salary", min_value=0),
        ],
    ),
}


def _connect():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user="DBT_TRANSFORMER",
        private_key_file=os.environ["DBT_PRIVATE_KEY_PATH"],
        role="TRANSFORMER",
        warehouse="RETAIL_WH",
        database="RETAIL_PULSE",
        schema="RAW",
    )


def _read(conn, table: str, columns: str) -> pd.DataFrame:
    cur = conn.cursor().execute(f"SELECT {columns} FROM {table}")
    df = pd.DataFrame(cur.fetchall(), columns=[c[0].lower() for c in cur.description])
    return df


def validate(df: pd.DataFrame, table: str, expectations: list) -> list[str]:
    """Return the list of failed checks (empty if all pass)."""
    context = gx.get_context(mode="ephemeral")
    os.environ.setdefault("TQDM_DISABLE", "1")
    batch_def = (
        context.data_sources.add_pandas("raw")
        .add_dataframe_asset(table)
        .add_batch_definition_whole_dataframe("whole")
    )
    suite = context.suites.add(gx.ExpectationSuite(name=table, expectations=expectations))
    definition = context.validation_definitions.add(
        gx.ValidationDefinition(name=table, data=batch_def, suite=suite)
    )
    result = definition.run(batch_parameters={"dataframe": df})
    return [
        f"{table}: {r.expectation_config.type} {r.expectation_config.kwargs.get('column', '')} "
        f"{r.result.get('unexpected_count', '')} bad rows".strip()
        for r in result.results
        if not r.success
    ]


def run_checks(tables: list[str] | None = None) -> dict[str, list[str]]:
    """Run the checks on the RAW tables and return {table: [errors]}; empty means pass."""
    conn = _connect()
    try:
        return {
            t: validate(_read(conn, t, TABLES[t][0]), t, TABLES[t][1]) for t in (tables or TABLES)
        }
    finally:
        conn.close()


def main() -> None:
    failures = {t: f for t, f in run_checks().items() if f}
    for t in TABLES:
        print(f"{'FAIL' if t in failures else 'OK  '} {t}")
        for line in failures.get(t, []):
            print(f"     - {line}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
