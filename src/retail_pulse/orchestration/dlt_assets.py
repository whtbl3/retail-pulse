from dagster import AssetExecutionContext, AssetKey
from dagster_dlt import DagsterDltResource, DagsterDltTranslator, dlt_assets
from dagster_dlt.translator import DltResourceTranslatorData

from retail_pulse.ingestion.pipelines import retail_pipeline, retail_source


class RetailDltTranslator(DagsterDltTranslator):
    # dbt source('raw', 'store') có key ["raw", "store"]; đặt key dlt trùng để lineage nối liền.
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
    yield from dlt_res.run(context=context)
