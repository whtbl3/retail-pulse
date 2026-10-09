SELECT
    {{ surrogate_key(['promotion_id']) }} AS promotion_key,
    promotion_id,
    CASE type
      WHEN 'percentage' THEN
          'Giảm ' || IFF(amount = TRUNC(amount),
                        TO_VARCHAR(TRUNC(amount)),
                        TO_VARCHAR(amount)) || '%'
      WHEN 'fixed_amount' THEN
              'Giảm ' || TO_VARCHAR(amount, 'FM999,999,999') || ' đ'
    END AS promotion_label,
    type   AS promotion_type,
    amount AS promotion_amount,
    start_date,
    end_date
FROM {{ ref('stg_promotion') }}

UNION ALL

-- Dòng hàng không có khuyến mãi (promotion_id rỗng ở fact)
SELECT
    -1             AS promotion_key,
    -1             AS promotion_id,
    'No promotion' AS promotion_label,
    NULL           AS promotion_type,
    NULL           AS promotion_amount,
    NULL           AS start_date,
    NULL           AS end_date

UNION ALL

-- Thành viên Unknown cho khóa chưa có trong dimension (dữ liệu đến trễ)
SELECT
    -2        AS promotion_key,
    -2        AS promotion_id,
    'Unknown' AS promotion_label,
    NULL      AS promotion_type,
    NULL      AS promotion_amount,
    NULL      AS start_date,
    NULL      AS end_date