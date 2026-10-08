SELECT
  transaction_id,
  store_id,
  employee_id,
  payment_method_id,
  transaction_ts,
  status,
  created_at,
  updated_at
FROM {{ source('raw', 'sales_transaction') }}
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY transaction_id, store_id, employee_id, payment_method_id, transaction_ts, status, created_at, updated_at
  ORDER BY _dlt_load_id
) = 1