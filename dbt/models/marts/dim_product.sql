SELECT
  {{ surrogate_key(['p.product_id', 'p.valid_from']) }} AS product_key,
  p.product_id,
  p.product_sku,
  p.product_name,
  p.category_id,
  c.category_name,
  p.brand_id,
  b.brand_name,
  p.unit_price,
  p.unit_cost,
  p.valid_from,
  p.valid_to,
  p.is_current
FROM {{ ref('int_product_scd2') }} AS p
LEFT JOIN {{ ref('stg_category') }} AS c ON p.category_id = c.category_id
LEFT JOIN {{ ref('stg_brand') }} AS b ON p.brand_id = b.brand_id

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2                                  AS product_key,
    -2                                  AS product_id,
    'Unknown'                           AS product_sku,
    'Unknown'                           AS product_name,
    NULL                                AS category_id,
    'Unknown'                           AS category_name,
    NULL                                AS brand_id,
    'Unknown'                           AS brand_name,
    NULL                                AS unit_price,
    NULL                                AS unit_cost,
    '1900-01-01'::timestamp_tz          AS valid_from,
    '9999-12-31'::timestamp_tz          AS valid_to,
    TRUE                                AS is_current