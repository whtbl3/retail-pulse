SELECT
  id AS promotion_id,
  type,
  amount,
  start_date,
  end_date
FROM {{ source('raw', 'promotion') }}