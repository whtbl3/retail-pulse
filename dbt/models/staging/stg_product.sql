SELECT
    id as product_id,
    product_sku,
    category_id,
    brand_id,
    product_name,
    unit_price,
    unit_cost,
    created_at,
    updated_at
FROM {{ source('raw', 'product') }}
QUALIFY ROW_NUMBER() OVER (
    -- Partition by every business column to find true duplicate rows
    PARTITION BY id, product_sku, category_id, brand_id, product_name, unit_price, unit_cost, created_at, updated_at
    -- Keep the row with the latest _dlt_load_id
    ORDER BY _dlt_load_id DESC
) = 1
