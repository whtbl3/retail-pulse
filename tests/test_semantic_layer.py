"""Semantic layer (specs 002 and 004): the metric definitions in dbt/models/semantic/.

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
HEADCOUNT_MODEL = "fct_store_headcount_monthly"

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
# Spec 004: on the store headcount snapshot
HEADCOUNT_METRICS = {
    "closing_headcount",
    "opening_headcount",
    "employee_months",
    "store_net_revenue",
    "joiners",
    "leavers",
    "revenue_per_employee",
}
SEMI_ADDITIVE = {"closing_headcount": "max", "opening_headcount": "min"}


@cache
def semantic_manifest() -> dict:
    return json.loads((DBT_DIR / "target" / "semantic_manifest.json").read_text())


@cache
def documented_columns(model: str = MODEL) -> set[str]:
    manifest = json.loads((DBT_DIR / "target" / "manifest.json").read_text())
    node = manifest["nodes"][f"model.retail_pulse.{model}"]
    return {name.lower() for name in node["columns"]}


def metrics() -> dict[str, dict]:
    return {m["name"]: m for m in semantic_manifest()["metrics"]}


def explain(metric: str, group_by: str | None = None) -> str:
    """SQL that MetricFlow generates for a metric, as the Preset sync will see it."""
    env = dict(os.environ)
    if env.get("DBT_PROFILES_DIR"):
        env["DBT_PROFILES_DIR"] = str(Path(env["DBT_PROFILES_DIR"]).resolve())
    result = subprocess.run(
        ["mf", "query", "--explain", "--metrics", metric]
        + (["--group-by", group_by] if group_by else []),
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


def test_the_metrics_are_exactly_the_agreed_ones():
    assert set(metrics()) == EXPECTED_METRICS | HEADCOUNT_METRICS


@pytest.mark.parametrize("name", sorted(EXPECTED_METRICS | HEADCOUNT_METRICS))
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


@pytest.mark.parametrize(
    ("semantic_model", "model"), [("sales", MODEL), ("store_headcount", HEADCOUNT_MODEL)]
)
def test_semantic_model_only_uses_documented_columns(semantic_model, model):
    """dbt-slim-ci builds the model and its documented columns; this ties the metrics to them."""
    [found] = [m for m in semantic_manifest()["semantic_models"] if m["name"] == semantic_model]
    assert columns_used(found) <= documented_columns(model)


def test_an_unknown_column_is_caught():
    fake = {"measures": [{"name": "x", "expr": "no_such_column"}]}
    assert not columns_used(fake) <= documented_columns()


# --- Store headcount snapshot (spec 004) ---


def headcount_measures() -> dict[str, dict]:
    [model] = [m for m in semantic_manifest()["semantic_models"] if m["name"] == "store_headcount"]
    return {m["name"]: m for m in model["measures"]}


@pytest.mark.parametrize(("measure", "window"), sorted(SEMI_ADDITIVE.items()))
def test_headcount_is_semi_additive_over_months(measure, window):
    """R7: summed across stores, but over several months only the last (first) month counts."""
    non_additive = headcount_measures()[measure]["non_additive_dimension"]
    assert non_additive["name"] == "month_start"
    assert non_additive["window_choice"] == window


def test_other_headcount_measures_are_additive():
    for name, measure in headcount_measures().items():
        if name not in SEMI_ADDITIVE:
            assert not measure.get("non_additive_dimension"), name


def test_closing_headcount_over_a_quarter_is_the_last_month():
    """AC9: by quarter and store, MetricFlow keeps only the quarter's last month, then sums."""
    sql = explain("closing_headcount", "metric_time__quarter,store_month__store_name")
    upper = " ".join(sql.split()).upper()
    assert "MAX(DATE_TRUNC('MONTH', MONTH_START))" in upper
    assert "GROUP BY DATE_TRUNC('QUARTER', MONTH_START)" in upper
    assert "SUM(SUBQ_2.__CLOSING_HEADCOUNT)" in upper


def test_revenue_per_employee_is_a_ratio_of_sums_with_no_division_by_zero():
    """R8, AC6, AC9: SUM(net revenue) / SUM(average headcount); no staff gives NULL, no error."""
    metric = metrics()["revenue_per_employee"]
    assert metric["type"] == "ratio"
    assert metric["type_params"]["numerator"]["name"] == "store_net_revenue"
    assert metric["type_params"]["denominator"]["name"] == "employee_months"
    sql = " ".join(explain("revenue_per_employee").split()).upper()
    assert "SUM(NET_REVENUE)" in sql
    assert "NULLIF(SUM(AVERAGE_HEADCOUNT), 0)" in sql
    assert "AVG(" not in sql


@pytest.mark.parametrize("name", sorted(HEADCOUNT_METRICS))
def test_headcount_metrics_read_only_the_snapshot(name):
    tree = sqlglot.parse_one(explain(name), dialect="snowflake")
    assert {table.name.lower() for table in tree.find_all(exp.Table)} == {HEADCOUNT_MODEL}
