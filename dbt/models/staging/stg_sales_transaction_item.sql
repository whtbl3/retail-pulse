SELECT
  transaction_id,
  line_number,
  product_id,
  promotion_id,
  quantity,
  regular_price,
  coupon_amount,
  created_at,
  updated_at
FROM {{ source('raw', 'sales_transaction_item') }}
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY transaction_id, line_number, product_id, promotion_id, quantity, regular_price, coupon_amount, created_at, updated_at
  ORDER BY _dlt_load_id DESC
) = 1