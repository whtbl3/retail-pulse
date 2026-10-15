-- Spec 004, AC1 and AC8: one row for every store and every month from date_start to the as-of month,
-- and exactly that last month is not closed. Returns a row when the count or the flags are wrong.
with snapshot as (
    select * from {{ ref('fct_store_headcount_monthly') }}
),

summary as (
    select
        count(*)                                                   as actual_rows,
        count(distinct as_of_date)                                 as as_of_dates,
        min(month_start)                                           as first_month,
        max(month_start)                                           as last_month,
        date_trunc('month', max(as_of_date))                       as as_of_month,
        datediff(month, '{{ var("date_start") }}'::date, max(as_of_date)) + 1 as expected_months,
        -- Rows whose flag is wrong: closed in the as-of month, or open in any other month
        count_if(is_month_closed = (month_start = date_trunc('month', as_of_date))) as wrong_flags
    from snapshot
),

stores as (
    select count(*) as store_count from {{ ref('dim_store') }} where store_key <> -2
)

select *
from summary
cross join stores
where actual_rows <> store_count * expected_months
   or as_of_dates <> 1
   or first_month <> '{{ var("date_start") }}'::date
   or last_month <> as_of_month
   or wrong_flags > 0
