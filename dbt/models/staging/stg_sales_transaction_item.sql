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
-- Chỉ giữ dòng của giao dịch completed (xem stg_sales_transaction).
WHERE transaction_id IN (SELECT transaction_id FROM {{ ref('stg_sales_transaction') }})
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY transaction_id, line_number, product_id, promotion_id, quantity, regular_price, coupon_amount, created_at, updated_at
  ORDER BY _dlt_load_id DESC
) = 1