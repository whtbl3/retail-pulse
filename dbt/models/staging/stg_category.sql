SELECT
  id AS category_id,
  category_name
FROM {{ source('raw', 'category') }}