SELECT
    {{ surrogate_key(['store_id']) }} AS store_key,
    store_id,
    store_name,
    address,
    phone_number
FROM {{ ref('stg_store') }}

UNION ALL

-- Unknown member for keys not yet in the dimension (late-arriving data)
SELECT
    -2 AS store_key,
    -2 AS store_id,
    'Unknown' AS store_name,
    'Unknown' AS address,
    'Unknown' AS phone_number