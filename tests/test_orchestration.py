from dagster import AssetKey

from retail_pulse.ingestion.pipelines import APPEND, FULL_REFRESH
from retail_pulse.orchestration.dlt_assets import retail_raw_assets


def test_one_asset_per_raw_table():
    expected = {AssetKey(["raw", t]) for t in [*APPEND, *FULL_REFRESH]}
    assert set(retail_raw_assets.keys) == expected
