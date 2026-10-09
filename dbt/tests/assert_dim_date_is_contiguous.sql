SELECT COUNT(*) AS n, MIN(full_date) AS d0, MAX(full_date) AS d1
FROM {{ ref('dim_date') }}
WHERE date_key <> -2
HAVING COUNT(*) <> {{ var('date_days') }}
    OR DATEDIFF(day, MIN(full_date), MAX(full_date)) + 1 <> COUNT(*)