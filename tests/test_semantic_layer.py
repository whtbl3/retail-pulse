"""Semantic layer (spec 002): the metric definitions in dbt/models/semantic/.

Needs dbt/target/manifest.json and semantic_manifest.json (`make dbt-parse`), as
test_orchestration does.
`mf query --explain` compiles SQL without connecting to Snowflake.
"""

import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

DBT_DIR = Path(__file__).parents[1] / "dbt"
MODEL = "fct_sales_enriched"

# Spec 002, Q2: the five metrics already on the dashboard plus three new ones
EXPECTED_METRICS = {
    "net_revenue",
    "gross_revenue",
    "discount_amount",
    "gross_profit",
    "quantity_sold",
    "gross_margin",
    "transaction_count",
    "average_basket_value",
}


@cache
def semantic_manifest() -> dict:
    return json.loads((DBT_DIR / "target" / "semantic_manifest.json").read_text())


@cache
def documented_columns() -> set[str]:
    manifest = json.loads((DBT_DIR / "target" / "manifest.json").read_text())
    node = manifest["nodes"][f"model.retail_pulse.{MODEL}"]
    return {name.lower() for name in node["columns"]}


def metrics() -> dict[str, dict]:
    return {m["name"]: m for m in semantic_manifest()["metrics"]}


def explain(metric: str) -> str:
    """SQL that MetricFlow generates for a metric, as the Preset sync will see it."""
    env = dict(os.environ)
    if env.get("DBT_PROFILES_DIR"):
        env["DBT_PROFILES_DIR"] = str(Path(env["DBT_PROFILES_DIR"]).resolve())
    result = subprocess.run(
        ["mf", "query", "--explain", "--metrics", metric],
        cwd=DBT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout[result.stdout.index("SELECT") :]


def columns_used(semantic_model: dict) -> set[str]:
    """Every column referenced by the entities, dimensions and measures of a semantic model."""
    used = set()
    for kind in ("entities", "dimensions", "measures"):
        for element in semantic_model.get(kind) or []:
            expr = element.get("expr") or element["name"]
            tree = sqlglot.parse_one(str(expr), dialect="snowflake")
            used |= {column.name.lower() for column in tree.find_all(exp.Column)}
    return used


def test_the_first_version_has_exactly_the_agreed_metrics():
    assert set(metrics()) == EXPECTED_METRICS


@pytest.mark.parametrize("name", sorted(EXPECTED_METRICS))
def test_every_metric_has_a_label_and_a_description(name):
    metric = metrics()[name]
    assert metric["label"]
    assert metric["description"]


def test_gross_margin_is_a_ratio_of_sums():
    metric = metrics()["gross_margin"]
    assert metric["type"] == "ratio"
    params = metric["type_params"]
    assert params["numerator"]["name"] == "gross_profit"
    assert params["denominator"]["name"] == "net_revenue"


@pytest.mark.parametrize("name", sorted(EXPECTED_METRICS))
def test_every_metric_compiles_to_one_table_without_joins(name):
    """The Preset sync turns a metric into one expression on one dataset; it rejects joins."""
    tree = sqlglot.parse_one(explain(name), dialect="snowflake")
    tables = {table.name.lower() for table in tree.find_all(exp.Table)}
    assert tables == {MODEL}
    assert not list(tree.find_all(exp.Join))


def test_net_revenue_is_the_sum_of_net_amount():
    sql = " ".join(explain("net_revenue").split()).upper()
    assert "SUM(NET_AMOUNT) AS NET_REVENUE" in sql


def test_gross_margin_divides_the_sums_not_row_ratios():
    sql = " ".join(explain("gross_margin").split()).upper()
    assert "SUM(GROSS_PROFIT)" in sql
    assert "SUM(NET_AMOUNT)" in sql
    assert "AVG(" not in sql


def test_semantic_model_only_uses_documented_columns():
    """dbt-slim-ci builds the model and its documented columns; this ties the metrics to them."""
    [sales] = [m for m in semantic_manifest()["semantic_models"] if m["name"] == "sales"]
    assert columns_used(sales) <= documented_columns()


def test_an_unknown_column_is_caught():
    fake = {"measures": [{"name": "x", "expr": "no_such_column"}]}
    assert not columns_used(fake) <= documented_columns()
