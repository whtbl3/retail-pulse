SELECT employee_id
FROM {{ ref('int_employee_scd2') }}
GROUP BY employee_id
HAVING COUNT_IF(is_current) <> 1