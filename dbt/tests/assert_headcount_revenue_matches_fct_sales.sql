-- Spec 004, AC4: net revenue per store and local month equals fct_sales, and the grand totals match.
-- A grand-total difference means fct_sales has rows with an Unknown (-2) store or date key; fix them
-- with the fct_sales full refresh (phase 5), not here.
with snapshot as (
    select store_id, month_start, net_revenue from {{ ref('fct_store_headcount_monthly') }}
),

sales as (
    select s.store_id, date_trunc('month', d.full_date) as month_start, sum(f.net_amount) as net_revenue
    from {{ ref('fct_sales') }} f
    join {{ ref('dim_store') }} s on f.store_key = s.store_key
    join {{ ref('dim_date') }} d  on f.date_key = d.date_key
    group by 1, 2
)

select 'store-month' as level, coalesce(sn.store_id, sa.store_id) as store_id,
       coalesce(sn.month_start, sa.month_start) as month_start,
       sn.net_revenue as snapshot_revenue, sa.net_revenue as sales_revenue
from snapshot sn
full join sales sa on sa.store_id = sn.store_id and sa.month_start = sn.month_start
where coalesce(sn.net_revenue, 0) <> coalesce(sa.net_revenue, 0)

union all

select 'total', null, null,
       (select sum(net_revenue) from snapshot),
       (select sum(net_amount) from {{ ref('fct_sales') }})
where (select sum(net_revenue) from snapshot)
      is distinct from (select sum(net_amount) from {{ ref('fct_sales') }})
