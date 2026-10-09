WITH minutes AS (
    SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS minute_of_day
    FROM TABLE(GENERATOR(ROWCOUNT => 1440))
),

parts AS (
    SELECT
        minute_of_day,
        FLOOR(minute_of_day / 60) AS hour_24,
        MOD(minute_of_day, 60)    AS minute
    FROM minutes
)

SELECT
    hour_24 * 100 + minute                          AS time_key,   -- 1435 = 14:35
    TIME_FROM_PARTS(hour_24, minute, 0)             AS time_of_day,
    hour_24,
    minute,
    IFF(hour_24 % 12 = 0, 12, hour_24 % 12)         AS hour_12,
    IFF(hour_24 < 12, 'AM', 'PM')                   AS am_pm,
    CASE
        WHEN hour_24 BETWEEN 6  AND 11 THEN 'Morning'
        WHEN hour_24 BETWEEN 12 AND 17 THEN 'Afternoon'
        WHEN hour_24 BETWEEN 18 AND 21 THEN 'Evening'
        ELSE 'Night'
    END                                             AS day_part
FROM parts

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension
SELECT
    -2        AS time_key,
    NULL      AS time_of_day,
    NULL      AS hour_24,
    NULL      AS minute,
    NULL      AS hour_12,
    'Unknown' AS am_pm,
    'Unknown' AS day_part