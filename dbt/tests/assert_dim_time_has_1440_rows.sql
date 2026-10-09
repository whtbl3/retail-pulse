SELECT COUNT(*) AS n
FROM {{ ref('dim_time') }}
WHERE time_key <> -2
HAVING COUNT(*) <> 1440