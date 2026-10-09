{% set w_latest = "OVER (PARTITION BY product_id ORDER BY updated_at DESC)" %}
{% set w_hist   = "OVER (PARTITION BY product_id ORDER BY updated_at)" %}

WITH versions AS (
    SELECT
        product_id,
        -- Type 1: luôn lấy giá trị mới nhất của sản phẩm
        FIRST_VALUE(product_sku)   {{ w_latest }} AS product_sku,
        FIRST_VALUE(product_name)  {{ w_latest }} AS product_name,
        -- Type 2: bốn cột theo dõi
        category_id,
        brand_id,
        unit_price,
        unit_cost,
        updated_at,
        LAG(category_id) {{ w_hist }} AS prev_category_id,
        LAG(brand_id)    {{ w_hist }} AS prev_brand_id,
        LAG(unit_price)  {{ w_hist }} AS prev_unit_price,
        LAG(unit_cost)   {{ w_hist }} AS prev_unit_cost,
        LAG(updated_at)  {{ w_hist }} AS prev_updated_at
    FROM {{ ref('stg_product') }}
),

change_points AS (
    SELECT *
    FROM versions
    WHERE prev_updated_at IS NULL
       OR prev_category_id IS DISTINCT FROM category_id
       OR prev_brand_id    IS DISTINCT FROM brand_id
       OR prev_unit_price  IS DISTINCT FROM unit_price
       OR prev_unit_cost   IS DISTINCT FROM unit_cost
)

SELECT
    product_id,
    product_sku,
    product_name,
    category_id,
    brand_id,
    unit_price,
    unit_cost,
    IFF(prev_updated_at IS NULL, '1900-01-01'::timestamp, updated_at) AS valid_from,
    COALESCE(LEAD(updated_at) {{ w_hist }}, '9999-12-31'::timestamp)   AS valid_to,
    LEAD(updated_at)          {{ w_hist }} IS NULL                     AS is_current
FROM change_points