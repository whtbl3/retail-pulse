select
    id as store_id,
    store_name,
    address,
    phone_number,
    created_at,
    updated_at
from {{ source('raw', 'store') }}
