SELECT
  {{ surrogate_key(['employee_id', 'valid_from']) }} AS employee_key,
  employee_id,
  store_id,
  employee_name,
  salary,
  address,
  start_date,
  end_date,
  valid_from,
  valid_to,
  is_current
FROM {{ ref('int_employee_scd2') }}

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2                                  AS employee_key,
    -2                                  AS employee_id,
    -2                                  AS store_id,
    'Unknown'                           AS employee_name,
    NULL                                AS salary,
    NULL                                AS address,
    NULL                                AS start_date,
    NULL                                AS end_date,
    '1900-01-01'::timestamp_tz          AS valid_from,
    '9999-12-31'::timestamp_tz          AS valid_to,
    TRUE                                AS is_current
