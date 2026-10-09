select transaction_id
from {{ source('raw', 'sales_transaction') }}
group by transaction_id
having count(distinct status) > 1