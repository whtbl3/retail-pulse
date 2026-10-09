SELECT product_id, MIN(valid_from) AS first_valid_from
FROM {{ ref('int_product_scd2') }}
GROUP BY product_id
HAVING MIN(valid_from) <> '1900-01-01'::timestamp