SELECT *
FROM {{ ref('int_product_scd2') }}
WHERE valid_to <= valid_from