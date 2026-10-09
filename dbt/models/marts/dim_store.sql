SELECT
    {{ surrogate_key(['store_id']) }} AS store_key,
    store_id,
    store_name,
    address,
    phone_number
FROM {{ ref('stg_store') }}

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2 AS store_key,
    -2 AS store_id,
    'Unknown' AS store_name,
    'Unknown' AS address,
    'Unknown' AS phone_number