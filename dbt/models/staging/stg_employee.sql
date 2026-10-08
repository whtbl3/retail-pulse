SELECT
  id AS employee_id,
  store_id,
  first_name,
  last_name,
  date_of_birth,
  address,
  phone_number,
  salary,
  start_date,
  end_date,
  created_at,
  updated_at
FROM {{ source('raw', 'employee') }}
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY id, store_id, first_name, last_name, date_of_birth, address, phone_number, salary, start_date, end_date, created_at, updated_at
  ORDER BY _dlt_load_id DESC
) = 1