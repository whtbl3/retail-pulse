SELECT
  product_id,
  promotion_id
FROM {{ source('raw', 'promotion_product') }}