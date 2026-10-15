-- fct_sales_enriched must keep every fact row exactly once: same row count and same totals as fct_sales.
-- A difference means a dimension join dropped or duplicated rows. With the unique test on
-- (transaction_id, line_number), an equal row count means every fact row appears exactly once, so any
-- breakdown (by category, store or month) adds up to the same totals as fct_sales.
select *
from (
    select
        (select count(*) from {{ ref('fct_sales') }})                  as fct_rows,
        (select count(*) from {{ ref('fct_sales_enriched') }})         as enriched_rows,
        (select sum(net_amount) from {{ ref('fct_sales') }})           as fct_net_amount,
        (select sum(net_amount) from {{ ref('fct_sales_enriched') }})  as enriched_net_amount,
        (select sum(gross_profit) from {{ ref('fct_sales') }})         as fct_gross_profit,
        (select sum(gross_profit) from {{ ref('fct_sales_enriched') }}) as enriched_gross_profit
)
where fct_rows <> enriched_rows
   or fct_net_amount is distinct from enriched_net_amount
   or fct_gross_profit is distinct from enriched_gross_profit
