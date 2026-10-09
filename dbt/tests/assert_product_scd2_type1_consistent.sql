SELECT product_id
FROM {{ ref('int_product_scd2') }}
GROUP BY product_id
HAVING COUNT(DISTINCT product_name) > 1
    OR COUNT(DISTINCT product_sku)  > 1