SELECT employee_id
FROM {{ ref('int_employee_scd2') }}
GROUP BY employee_id
HAVING MIN(valid_from) <> '1900-01-01'::timestamp