SELECT
  id AS brand_id,
  brand_name
FROM {{ source('raw', 'brand') }}