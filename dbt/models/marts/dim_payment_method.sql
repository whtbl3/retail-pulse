-- Thử slim CI: sửa nhỏ để dbt thấy model này đã đổi (state:modified).
SELECT
    {{ surrogate_key(['payment_method_id']) }} AS payment_method_key,
    payment_method_id,
    method AS payment_method_name
FROM {{ ref('stg_payment_method') }}

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2 AS payment_method_key,
    -2 AS payment_method_id,
    'Unknown' AS payment_method_name