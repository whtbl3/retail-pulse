SELECT employee_id, valid_from, valid_to, next_valid_from
FROM (
    SELECT employee_id, valid_from, valid_to,
           LEAD(valid_from) OVER (PARTITION BY employee_id ORDER BY valid_from) AS next_valid_from
    FROM {{ ref('int_employee_scd2') }}
)
WHERE next_valid_from IS NOT NULL
  AND next_valid_from <> valid_to