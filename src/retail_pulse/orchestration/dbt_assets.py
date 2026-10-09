import os
from pathlib import Path

from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

# .../repo/src/retail_pulse/orchestration/dbt_assets.py -> parents[3] là thư mục gốc repo
# profiles.yml nằm ngoài repo (~/.dbt); ghi đè bằng DBT_PROFILES_DIR. Phải truyền cho DbtProject,
# vì prepare_if_dev tạo DbtCliResource từ nó để chạy `dbt deps` và `dbt parse`.
dbt_project = DbtProject(
    project_dir=Path(__file__).parents[3] / "dbt",
    profiles_dir=os.environ.get("DBT_PROFILES_DIR", str(Path.home() / ".dbt")),
)
dbt_project.prepare_if_dev()


@dbt_assets(manifest=dbt_project.manifest_path)
def retail_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
