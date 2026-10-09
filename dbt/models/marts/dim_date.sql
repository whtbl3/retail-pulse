WITH days AS (
    SELECT
        DATEADD(day, ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1,
                '{{ var("date_start") }}'::date) AS full_date
    FROM TABLE(GENERATOR(ROWCOUNT => {{ var('date_days') }}))
)

SELECT
    TO_NUMBER(TO_CHAR(full_date, 'YYYYMMDD')) AS date_key,
    full_date,
    YEAR(full_date)         AS year,
    QUARTER(full_date)      AS quarter,
    MONTH(full_date)        AS month,
    DECODE(MONTH(full_date),
           1, 'January', 2, 'February', 3, 'March', 4, 'April', 5, 'May', 6, 'June',
           7, 'July', 8, 'August', 9, 'September', 10, 'October', 11, 'November', 12, 'December'
          )                    AS month_name,
    DAY(full_date)          AS day_of_month,
    DAYOFWEEKISO(full_date) AS day_of_week,    -- 1 = Monday ... 7 = Sunday
    DECODE(DAYOFWEEKISO(full_date),
           1, 'Monday', 2, 'Tuesday', 3, 'Wednesday', 4, 'Thursday',
           5, 'Friday', 6, 'Saturday', 7, 'Sunday') AS day_name,
    WEEKISO(full_date)      AS week_of_year,
    DAYOFWEEKISO(full_date) IN (6, 7) AS is_weekend
FROM days

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension
SELECT
    -2        AS date_key,
    NULL      AS full_date,
    NULL      AS year,
    NULL      AS quarter,
    NULL      AS month,
    'Unknown' AS month_name,
    NULL      AS day_of_month,
    NULL      AS day_of_week,
    'Unknown' AS day_name,
    NULL      AS week_of_year,
    NULL      AS is_weekend