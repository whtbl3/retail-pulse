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
    -- Gom nhóm theo tất cả các cột dữ liệu nghiệp vụ để xác định dòng trùng lặp thực sự
    PARTITION BY id, product_sku, category_id, brand_id, product_name, unit_price, unit_cost, created_at, updated_at
    -- Chọn bản ghi có _dlt_load_id mới nhất làm đại diện
    ORDER BY _dlt_load_id DESC
) = 1
