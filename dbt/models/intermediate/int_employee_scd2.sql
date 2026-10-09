{% set w_latest = "OVER (PARTITION BY employee_id ORDER BY updated_at DESC)" %}
{% set w_hist   = "OVER (PARTITION BY employee_id ORDER BY updated_at)" %}

WITH versions AS (
    SELECT
        employee_id,
        -- Type 1: luôn lấy giá trị mới nhất của nhân viên
        CONCAT(
            FIRST_VALUE(first_name) {{ w_latest }}, ' ',
            FIRST_VALUE(last_name)  {{ w_latest }}
        ) AS employee_name,
        FIRST_VALUE(salary)     {{ w_latest }} AS salary,
        FIRST_VALUE(address)    {{ w_latest }} AS address,
        FIRST_VALUE(start_date) {{ w_latest }} AS start_date,
        FIRST_VALUE(end_date)   {{ w_latest }} AS end_date,
        -- Type 2: chỉ store_id
        store_id,
        updated_at,
        LAG(store_id)   {{ w_hist }} AS prev_store_id,
        LAG(updated_at) {{ w_hist }} AS prev_updated_at
    FROM {{ ref('stg_employee') }}
),

change_points AS (
    SELECT *
    FROM versions
    WHERE prev_updated_at IS NULL
       OR prev_store_id IS DISTINCT FROM store_id
)

SELECT
    employee_id,
    employee_name,
    store_id,
    salary,
    address,
    start_date,
    end_date,
    IFF(prev_updated_at IS NULL, '1900-01-01'::timestamp, updated_at) AS valid_from,
    COALESCE(LEAD(updated_at) {{ w_hist }}, '9999-12-31'::timestamp)  AS valid_to,
    LEAD(updated_at) {{ w_hist }} IS NULL                             AS is_current
FROM change_points