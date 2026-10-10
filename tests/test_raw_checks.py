import pandas as pd

from retail_pulse.quality.raw_checks import TABLES, validate


def _check(table, df):
    return validate(df, table, TABLES[table][1])


def test_clean_product_passes():
    df = pd.DataFrame(
        {
            "id": [1],
            "product_sku": ["A"],
            "unit_price": [10.0],
            "unit_cost": [5.0],
            "updated_at": [pd.Timestamp("2026-01-01")],
        }
    )
    assert _check("product", df) == []


def test_bad_status_and_null_key_are_caught():
    df = pd.DataFrame(
        {
            "transaction_id": [1, None],
            "store_id": [1, 1],
            "employee_id": [1, 1],
            "payment_method_id": [1, 1],
            "transaction_ts": [pd.Timestamp("2026-01-01")] * 2,
            "status": ["completed", "refunded"],
            "updated_at": [pd.Timestamp("2026-01-01")] * 2,
        }
    )
    failures = " ".join(_check("sales_transaction", df))
    assert "transaction_id" in failures and "status" in failures
