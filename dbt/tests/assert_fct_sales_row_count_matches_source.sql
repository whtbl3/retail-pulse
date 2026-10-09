select 1
from (
    select
        (select count(*)
         from {{ ref('stg_sales_transaction_item') }} i
         join {{ ref('stg_sales_transaction') }} t using (transaction_id)) as src_rows,
        (select count(*) from {{ ref('fct_sales') }}) as fct_rows
)
where src_rows <> fct_rows