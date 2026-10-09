WITH ordered AS (
    SELECT
        product_id, valid_from,
        category_id, brand_id, unit_price, unit_cost,
        LAG(category_id) OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_category_id,
        LAG(brand_id)    OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_brand_id,
        LAG(unit_price)  OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_unit_price,
        LAG(unit_cost)   OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_unit_cost,
        LAG(valid_from)  OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_valid_from
    FROM {{ ref('int_product_scd2') }}
)
SELECT *
FROM ordered
WHERE prev_valid_from IS NOT NULL
  AND prev_category_id IS NOT DISTINCT FROM category_id
  AND prev_brand_id    IS NOT DISTINCT FROM brand_id
  AND prev_unit_price  IS NOT DISTINCT FROM unit_price
  AND prev_unit_cost   IS NOT DISTINCT FROM unit_cost