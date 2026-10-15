"""Freshness of the incremental RAW tables (spec 001, R5): a stale table warns and never blocks.

The limits live in dbt/models/staging/___sources.yml (warn after 26 hours, error after 3 days on
updated_at). This check runs `dbt source freshness` once and reports one result per table. Both a
dbt warn and a dbt error become a failed check with severity WARN, so dbt still builds what arrived.
"""

from collections.abc import Iterator

from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetKey,
    multi_asset_check,
)
from dagster_dbt import DbtCliResource

from retail_pulse.ingestion.pipelines import APPEND

FRESHNESS_TABLES: list[str] = list(APPEND)


def results_from_sources(sources: dict) -> Iterator[AssetCheckResult]:
    """Turn dbt's target/sources.json into one check result per incremental RAW table."""
    by_table = {r["unique_id"].split(".")[-1]: r for r in sources.get("results", [])}
    for table in FRESHNESS_TABLES:
        result = by_table.get(table)
        if result is None:
            yield AssetCheckResult(
                asset_key=AssetKey(["raw", table]),
                check_name="freshness",
                passed=False,
                severity=AssetCheckSeverity.WARN,
                metadata={"dbt_status": "missing from sources.json"},
            )
            continue
        metadata = {"dbt_status": result["status"]}
        age = result.get("max_loaded_at_time_ago_in_s")
        if age is not None:
            metadata["hours_since_newest_row"] = round(age / 3600, 1)
        if result.get("max_loaded_at"):
            metadata["newest_row_at"] = result["max_loaded_at"]
        if result.get("error"):
            metadata["error"] = result["error"]
        yield AssetCheckResult(
            asset_key=AssetKey(["raw", table]),
            check_name="freshness",
            passed=result["status"] == "pass",
            severity=AssetCheckSeverity.WARN,
            metadata=metadata,
        )


@multi_asset_check(
    specs=[
        AssetCheckSpec(
            name="freshness",
            asset=AssetKey(["raw", table]),
            blocking=False,
            description="dbt source freshness on updated_at: warn after 26 h, error after 3 days",
        )
        for table in FRESHNESS_TABLES
    ],
    name="raw_freshness",
)
def raw_freshness_check(
    context: AssetCheckExecutionContext, dbt: DbtCliResource
) -> Iterator[AssetCheckResult]:
    selection = " ".join(f"source:raw.{table}" for table in FRESHNESS_TABLES)
    # dbt exits non-zero when a source is past error_after; that is a warning here, not a failure
    invocation = dbt.cli(["source", "freshness", "--select", selection], raise_on_error=False)
    invocation.wait()
    yield from results_from_sources(invocation.get_artifact("sources.json"))
