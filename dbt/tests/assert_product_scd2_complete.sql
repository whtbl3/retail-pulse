SELECT DISTINCT s.product_id
FROM {{ ref('stg_product') }} s
LEFT JOIN {{ ref('int_product_scd2') }} d
  ON s.product_id = d.product_id
WHERE d.product_id IS NULL