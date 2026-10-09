"""Dagster: điều phối dlt (Postgres -> Snowflake RAW) rồi dbt (staging -> marts)."""

from dagster import Definitions
from dagster_dbt import DbtCliResource
from dagster_dlt import DagsterDltResource

from retail_pulse.orchestration.dbt_assets import dbt_project, retail_dbt_assets
from retail_pulse.orchestration.dlt_assets import retail_raw_assets
from retail_pulse.orchestration.jobs import (
    daily_pipeline_schedule,
    fct_sales_full_refresh_job,
    full_pipeline_job,
)

defs = Definitions(
    assets=[retail_raw_assets, retail_dbt_assets],
    jobs=[full_pipeline_job, fct_sales_full_refresh_job],
    schedules=[daily_pipeline_schedule],
    resources={
        "dlt_res": DagsterDltResource(),
        "dbt": DbtCliResource(project_dir=dbt_project),  # profiles_dir lấy từ dbt_project
    },
)
