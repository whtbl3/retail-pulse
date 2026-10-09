"""Job: nhóm asset thành một lần chạy có tên, và lịch chạy cho full_pipeline."""

from dagster import (
    AssetKey,
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)

from retail_pulse.orchestration.dbt_assets import retail_dbt_assets
from retail_pulse.orchestration.dlt_assets import retail_raw_assets

# Nạp RAW bằng dlt, rồi dbt build (model và test) theo đúng thứ tự phụ thuộc của đồ thị asset.
full_pipeline_job = define_asset_job(
    name="full_pipeline",
    selection=AssetSelection.assets(retail_raw_assets, retail_dbt_assets),
    description="dlt nạp RAW, rồi dbt build toàn bộ (gồm test).",
)

# Chỉ dựng lại fct_sales từ đầu (sửa dòng khóa -2); không đụng RAW. Tag làm asset dbt thêm
# --full-refresh (xem dbt_assets.py).
fct_sales_full_refresh_job = define_asset_job(
    name="fct_sales_full_refresh",
    selection=AssetSelection.assets(AssetKey(["marts", "fct_sales"])),
    tags={"full_refresh": "true"},
    description="dbt build --full-refresh cho fct_sales. Không chạy dlt, không đụng RAW.",
)

# 23:00 giờ VN, sau giờ đóng cửa (22:00) nên đã đủ đơn trong ngày.
# fct_sales_full_refresh không có lịch: chạy tay khi cần.
daily_pipeline_schedule = ScheduleDefinition(
    job=full_pipeline_job,
    cron_schedule="0 23 * * *",
    execution_timezone="Asia/Ho_Chi_Minh",
    default_status=DefaultScheduleStatus.RUNNING,
)
