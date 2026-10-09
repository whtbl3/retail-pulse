SELECT *
FROM {{ ref('int_employee_scd2') }}
WHERE valid_to <= valid_from