from dagster import AssetExecutionContext, AssetKey, RetryRequested
from dagster_dlt import DagsterDltResource, DagsterDltTranslator, dlt_assets
from dagster_dlt.translator import DltResourceTranslatorData

from retail_pulse.ingestion.pipelines import retail_pipeline, retail_source

# Ingestion is the only step that retries (spec 001, R4): a dropped connection to Postgres or
# Snowflake is often gone a few minutes later. dbt and quality checks fail the same way every time.
INGEST_MAX_RETRIES = 2
INGEST_RETRY_SECONDS = 300


class RetailDltTranslator(DagsterDltTranslator):
    # dbt source('raw', 'store') has key ["raw", "store"]; matching dlt keys join the lineage.
    def get_asset_spec(self, data: DltResourceTranslatorData):
        default_spec = super().get_asset_spec(data)
        return default_spec.replace_attributes(
            key=AssetKey(["raw", data.resource.name]),
        )


@dlt_assets(
    dlt_source=retail_source(),
    dlt_pipeline=retail_pipeline(),
    name="retail_raw",
    group_name="raw",
    dagster_dlt_translator=RetailDltTranslator(),
)
def retail_raw_assets(context: AssetExecutionContext, dlt_res: DagsterDltResource):
    # dlt_assets takes no retry_policy, so the body asks for the retry itself. A rerun is safe: dlt
    # keeps its incremental state and staging drops rows reloaded at the cursor boundary.
    try:
        yield from dlt_res.run(context=context)
    except Exception as exc:
        raise RetryRequested(
            max_retries=INGEST_MAX_RETRIES, seconds_to_wait=INGEST_RETRY_SECONDS
        ) from exc
