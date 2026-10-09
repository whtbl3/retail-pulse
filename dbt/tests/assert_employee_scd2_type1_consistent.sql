SELECT employee_id
FROM {{ ref('int_employee_scd2') }}
GROUP BY employee_id
HAVING COUNT(DISTINCT HASH(employee_name, salary, address, start_date, end_date)) > 1