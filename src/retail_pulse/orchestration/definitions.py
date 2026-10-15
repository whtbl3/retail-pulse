"""Dagster: orchestrates dlt (Postgres -> Snowflake RAW), then dbt (staging -> marts)."""

from dagster import Definitions
from dagster_dbt import DbtCliResource
from dagster_dlt import DagsterDltResource

from retail_pulse.orchestration.alerts import slack_on_run_failure
from retail_pulse.orchestration.dbt_assets import dbt_project, retail_dbt_assets
from retail_pulse.orchestration.dlt_assets import retail_raw_assets
from retail_pulse.orchestration.freshness import raw_freshness_check
from retail_pulse.orchestration.jobs import (
    daily_pipeline_schedule,
    fct_sales_full_refresh_job,
    full_pipeline_job,
)
from retail_pulse.orchestration.quality_checks import raw_quality_checks

defs = Definitions(
    assets=[retail_raw_assets, retail_dbt_assets],
    asset_checks=[*raw_quality_checks, raw_freshness_check],
    jobs=[full_pipeline_job, fct_sales_full_refresh_job],
    schedules=[daily_pipeline_schedule],
    sensors=[slack_on_run_failure],
    resources={
        "dlt_res": DagsterDltResource(),
        "dbt": DbtCliResource(project_dir=dbt_project),  # profiles_dir comes from dbt_project
    },
)
