-- One row per store, as in the OLTP table; ids renamed to *_id. No history: stores are Type 1 (spec §10.2).
select
    id as store_id,
    store_name,
    address,
    phone_number,
    created_at,
    updated_at
from {{ source('raw', 'store') }}
