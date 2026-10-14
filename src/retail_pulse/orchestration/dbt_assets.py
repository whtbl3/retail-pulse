import os
from pathlib import Path

from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

# .../repo/src/retail_pulse/orchestration/dbt_assets.py -> parents[3] is the repo root
# profiles.yml lives outside the repo (~/.dbt); override with DBT_PROFILES_DIR. It must be passed
# to DbtProject: prepare_if_dev builds a DbtCliResource from it to run `dbt deps` and `dbt parse`.
dbt_project = DbtProject(
    project_dir=Path(__file__).parents[3] / "dbt",
    profiles_dir=os.environ.get("DBT_PROFILES_DIR", str(Path.home() / ".dbt")),
)
dbt_project.prepare_if_dev()


@dbt_assets(manifest=dbt_project.manifest_path)
def retail_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    args = ["build"]
    # Job fct_sales_full_refresh sets this tag; dbt rebuilds only the assets selected in that run
    if context.run.tags.get("full_refresh") == "true":
        args.append("--full-refresh")
    yield from dbt.cli(args, context=context).stream()
