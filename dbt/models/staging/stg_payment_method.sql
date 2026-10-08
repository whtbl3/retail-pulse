SELECT
  id AS payment_method_id,
  method
FROM {{ source('raw', 'payment_method') }}