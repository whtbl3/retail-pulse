SELECT employee_id, valid_from
FROM (
    SELECT employee_id, valid_from, store_id,
           LAG(store_id) OVER (PARTITION BY employee_id ORDER BY valid_from) AS prev_store_id
    FROM {{ ref('int_employee_scd2') }}
)
WHERE prev_store_id IS NOT DISTINCT FROM store_id
  AND prev_store_id IS NOT NULL