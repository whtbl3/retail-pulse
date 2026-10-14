"""Great Expectations asset checks on RAW. blocking=True: a failure stops downstream dbt."""

from dagster import AssetCheckResult, AssetKey, asset_check

from retail_pulse.quality.raw_checks import TABLES, run_checks


def _make_check(table: str):
    @asset_check(asset=AssetKey(["raw", table]), name="great_expectations", blocking=True)
    def check() -> AssetCheckResult:
        failures = run_checks([table])[table]
        return AssetCheckResult(passed=not failures, metadata={"failures": failures or "none"})

    return check


raw_quality_checks = [_make_check(t) for t in TABLES]
