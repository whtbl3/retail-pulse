SELECT
    product_id,
    COUNT_IF(is_current) AS current_rows
FROM {{ ref('int_product_scd2') }}
GROUP BY product_id
HAVING COUNT_IF(is_current) <> 1