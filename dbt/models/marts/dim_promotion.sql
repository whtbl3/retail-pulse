SELECT
    {{ surrogate_key(['promotion_id']) }} AS promotion_key,
    promotion_id,
    CASE type
      WHEN 'percentage' THEN
          IFF(amount = TRUNC(amount),
              TO_VARCHAR(TRUNC(amount)),
              TO_VARCHAR(amount)) || '% off'
      WHEN 'fixed_amount' THEN
          TO_VARCHAR(amount, 'FM999,999,999') || ' VND off'
    END AS promotion_label,
    type   AS promotion_type,
    amount AS promotion_amount,
    start_date,
    end_date
FROM {{ ref('stg_promotion') }}

UNION ALL

-- Line items without a promotion (null promotion_id in the fact)
SELECT
    -1             AS promotion_key,
    -1             AS promotion_id,
    'No promotion' AS promotion_label,
    NULL           AS promotion_type,
    NULL           AS promotion_amount,
    NULL           AS start_date,
    NULL           AS end_date

UNION ALL

-- Unknown member for keys not yet in the dimension (late-arriving data)
SELECT
    -2        AS promotion_key,
    -2        AS promotion_id,
    'Unknown' AS promotion_label,
    NULL      AS promotion_type,
    NULL      AS promotion_amount,
    NULL      AS start_date,
    NULL      AS end_date