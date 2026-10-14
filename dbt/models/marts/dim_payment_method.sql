SELECT
    {{ surrogate_key(['payment_method_id']) }} AS payment_method_key,
    payment_method_id,
    method AS payment_method_name
FROM {{ ref('stg_payment_method') }}

UNION ALL

-- Unknown member for keys not yet in the dimension (late-arriving data)
SELECT
    -2 AS payment_method_key,
    -2 AS payment_method_id,
    'Unknown' AS payment_method_name