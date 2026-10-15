"""`make preset-zip` (spec 002): the Preset import ZIP built from the MetricFlow metrics.

The last test calls `mf query --explain`, so it needs `make dbt-parse` like test_semantic_layer.
"""

import io
import zipfile

import pytest
import yaml

from retail_pulse.semantic import preset_export as pe

DB_UUID = "11111111-2222-3333-4444-555555555555"

# What the real metrics compile to (checked by the last test)
EXPECTED = {
    "average_basket_value": "SUM(net_amount) / NULLIF(COUNT(DISTINCT transaction_id), 0)",
    "discount_amount": "SUM(discount_amount)",
    "gross_margin": (
        "CAST(SUM(gross_profit) AS DOUBLE) / CAST(NULLIF(SUM(net_amount), 0) AS DOUBLE)"
    ),
    "gross_profit": "SUM(gross_profit)",
    "gross_revenue": "SUM(gross_amount)",
    "net_revenue": "SUM(net_amount)",
    "quantity_sold": "SUM(quantity)",
    "transaction_count": "COUNT(DISTINCT transaction_id)",
}

SIMPLE_SQL = "SELECT SUM(net_amount) AS net_revenue FROM RETAIL_PULSE.marts.fct_sales_enriched s"
DERIVED_SQL = """
SELECT net_revenue / nullif(transaction_count, 0) AS average_basket_value
FROM (
  SELECT SUM(net_amount) AS net_revenue, COUNT(DISTINCT transaction_id) AS transaction_count
  FROM RETAIL_PULSE.marts.fct_sales_enriched s
) subq_5
"""


def test_simple_metric_becomes_its_aggregate():
    assert pe.to_expression(SIMPLE_SQL) == "SUM(net_amount)"


def test_derived_metric_inlines_the_subquery_aggregates():
    assert pe.to_expression(DERIVED_SQL) == EXPECTED["average_basket_value"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(f.net_amount) AS x FROM a f JOIN b d ON f.k = d.k",
        "SELECT SUM(net_amount) AS x FROM a WHERE store_name = 'X'",
        "SELECT SUM(net_amount) AS x, SUM(quantity) AS y FROM a",
    ],
)
def test_metrics_that_one_expression_cannot_hold_are_refused(sql):
    with pytest.raises(ValueError):
        pe.to_expression(sql)


def make_export(path, databases=1, datasets=1):
    """A ZIP shaped like a Preset dataset export."""
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("dataset_export_x/metadata.yaml", "version: 1.0.0\ntype: SqlaTable\n")
        for i in range(databases):
            database = {
                "database_name": "RetailPulse",
                "sqlalchemy_uri": "snowflake://PRESET_READER:XXXXXXXXXX@acct/RETAIL_PULSE/MARTS",
                "uuid": DB_UUID if i == 0 else f"{DB_UUID[:-1]}{i}",
            }
            bundle.writestr(f"dataset_export_x/databases/RetailPulse{i}.yaml", yaml.dump(database))
        for i in range(datasets):
            dataset = {
                "table_name": "sales_enriched",
                "sql": "select 1",
                "offset": 0,
                "uuid": "99999999-0000-0000-0000-000000000000",
                "version": "1.0.0",
                "database_uuid": DB_UUID,
            }
            bundle.writestr(
                f"dataset_export_x/datasets/RetailPulse0/sales_enriched_{i}.yaml",
                yaml.dump(dataset),
            )
    return path


def fake_sql(metric):
    return f"SELECT SUM({metric}) AS {metric} FROM RETAIL_PULSE.marts.fct_sales_enriched s"


def read_bundle(path):
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as bundle:
        return {name: bundle.read(name).decode() for name in bundle.namelist()}


def test_bundle_has_the_dataset_on_the_existing_connection(tmp_path):
    export = make_export(tmp_path / "export.zip")
    out = pe.build(export, tmp_path / "out.zip", compile_sql=fake_sql)

    files = read_bundle(out)
    root = pe.ROOT
    assert files[f"{root}/metadata.yaml"] == "version: 1.0.0\ntype: SqlaTable\n"
    assert yaml.safe_load(files[f"{root}/databases/RetailPulse0.yaml"])["uuid"] == DB_UUID

    dataset = yaml.safe_load(files[f"{root}/datasets/RetailPulse0/FCT_SALES_ENRICHED.yaml"])
    assert dataset["table_name"] == "FCT_SALES_ENRICHED"
    assert dataset["schema"] == "MARTS"
    assert dataset["sql"] is None  # physical dataset, not the old virtual one
    assert dataset["database_uuid"] == DB_UUID
    assert dataset["uuid"] == pe.DATASET_UUID
    assert dataset["main_dttm_col"] == "FULL_DATE"
    assert {m["metric_name"] for m in dataset["metrics"]} == set(EXPECTED)
    assert all(m["verbose_name"] and m["description"] for m in dataset["metrics"])
    assert {"FULL_DATE", "STORE_NAME", "NET_AMOUNT"} <= {
        c["column_name"] for c in dataset["columns"]
    }


def test_a_second_build_keeps_the_same_uuids(tmp_path):
    export = make_export(tmp_path / "export.zip")
    first = read_bundle(pe.build(export, tmp_path / "a.zip", compile_sql=fake_sql))
    second = read_bundle(pe.build(export, tmp_path / "b.zip", compile_sql=fake_sql))
    assert first == second


@pytest.mark.parametrize(("databases", "datasets"), [(0, 1), (2, 1), (1, 0)])
def test_an_export_that_is_not_one_dataset_on_one_connection_is_refused(
    tmp_path, databases, datasets
):
    export = make_export(tmp_path / "export.zip", databases=databases, datasets=datasets)
    with pytest.raises(ValueError):
        pe.build(export, tmp_path / "out.zip", compile_sql=fake_sql)


def test_the_real_metrics_convert_to_the_expected_expressions():
    expressions = {m["name"]: pe.to_expression(pe.explain(m["name"])) for m in pe.load_metrics()}
    assert expressions == EXPECTED


def test_profiles_come_from_the_env_var_then_the_project_then_home(tmp_path, monkeypatch):
    """`mf` only looks in DBT_PROFILES_DIR and the current folder; dbt also looks in ~/.dbt."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = tmp_path / "dbt"
    project.mkdir()
    assert pe.profiles_dir(project, env={}) == tmp_path / "home" / ".dbt"
    (project / "profiles.yml").write_text("retail_pulse: {}\n")
    assert pe.profiles_dir(project, env={}) == project.resolve()
    custom = tmp_path / "ci"
    assert pe.profiles_dir(project, env={"DBT_PROFILES_DIR": str(custom)}) == custom.resolve()


def test_an_mf_failure_shows_its_error(tmp_path):
    (tmp_path / "dbt_project.yml").write_text("name: x\nprofile: no_such_profile\n")
    with pytest.raises(ValueError, match="mf query --explain failed for metric net_revenue"):
        pe.explain("net_revenue", tmp_path)
