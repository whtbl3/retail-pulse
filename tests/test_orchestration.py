from dagster import AssetKey

from retail_pulse.ingestion.pipelines import APPEND, FULL_REFRESH
from retail_pulse.orchestration.dlt_assets import retail_raw_assets


def test_one_asset_per_raw_table():
    expected = {AssetKey(["raw", t]) for t in [*APPEND, *FULL_REFRESH]}
    assert set(retail_raw_assets.keys) == expected


def test_jobs_are_registered_with_expected_selection():
    from dagster import AssetKey

    from retail_pulse.orchestration.definitions import defs

    assert {j.name for j in defs.jobs} == {"full_pipeline", "fct_sales_full_refresh"}
    full = defs.resolve_job_def("full_pipeline")
    only_fct = defs.resolve_job_def("fct_sales_full_refresh")

    keys = {k.to_user_string() for k in full.asset_layer.executable_asset_keys}
    assert "raw/product" in keys and "marts/fct_sales" in keys

    assert set(only_fct.asset_layer.executable_asset_keys) == {AssetKey(["marts", "fct_sales"])}
    assert only_fct.tags == {"full_refresh": "true"}
    assert "full_refresh" not in full.tags


def test_daily_schedule_targets_full_pipeline():
    from retail_pulse.orchestration.definitions import defs

    schedule = defs.resolve_schedule_def("full_pipeline_schedule")
    assert schedule.cron_schedule == "0 23 * * *"
    assert schedule.execution_timezone == "Asia/Ho_Chi_Minh"
