SELECT
  {{ surrogate_key(['product_id', 'valid_from']) }} AS product_key,
  product_id,
  product_sku,
  product_name,
  category_id,
  brand_id,
  unit_price,
  unit_cost,
  valid_from,
  valid_to,
  is_current
FROM {{ ref('int_product_scd2') }}

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2                                  AS product_key,
    -2                                  AS product_id,
    'Unknown'                           AS product_sku,
    'Unknown'                           AS product_name,
    NULL                                AS category_id,
    NULL                                AS brand_id,
    NULL                                AS unit_price,
    NULL                                AS unit_cost,
    '1900-01-01'::timestamp_tz          AS valid_from,
    '9999-12-31'::timestamp_tz          AS valid_to,
    TRUE                                AS is_current