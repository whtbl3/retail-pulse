"""Jobs: group assets into named runs, plus the schedule for full_pipeline."""

from dagster import (
    AssetKey,
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)

from retail_pulse.orchestration.dbt_assets import retail_dbt_assets
from retail_pulse.orchestration.dlt_assets import retail_raw_assets

# Load RAW with dlt, then dbt build (models and tests) in the asset graph's dependency order.
full_pipeline_job = define_asset_job(
    name="full_pipeline",
    selection=AssetSelection.assets(retail_raw_assets, retail_dbt_assets),
    description="dlt loads RAW, then dbt builds everything (tests included).",
)

# Only rebuild fct_sales from scratch (fixes -2 key rows); leaves RAW alone. The tag makes the
# dbt asset add --full-refresh (see dbt_assets.py).
fct_sales_full_refresh_job = define_asset_job(
    name="fct_sales_full_refresh",
    selection=AssetSelection.assets(AssetKey(["marts", "fct_sales"])),
    tags={"full_refresh": "true"},
    description="dbt build --full-refresh for fct_sales. Does not run dlt or touch RAW.",
)

# 23:00 Vietnam time, after closing (22:00), so the day's orders are all in.
# fct_sales_full_refresh has no schedule: run it by hand when needed.
daily_pipeline_schedule = ScheduleDefinition(
    job=full_pipeline_job,
    cron_schedule="0 23 * * *",
    execution_timezone="Asia/Ho_Chi_Minh",
    default_status=DefaultScheduleStatus.RUNNING,
)
