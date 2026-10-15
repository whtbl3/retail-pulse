-- Spec 004, AC1 and AC8: one row for every store and every month from date_start to the as-of month,
-- and exactly that last month is not closed. Returns a row when the count or the flags are wrong.
with snapshot as (
    select * from {{ ref('fct_store_headcount_monthly') }}
),

expected as (
    select
        (select count(*) from {{ ref('dim_store') }} where store_key <> -2)
        * (datediff(month, '{{ var("date_start") }}'::date, max(as_of_date)) + 1) as expected_rows,
        date_trunc('month', max(as_of_date))                                        as as_of_month
    from snapshot
)

select *
from expected e
where e.expected_rows <> (select count(*) from snapshot)
   or (select min(month_start) from snapshot) <> '{{ var("date_start") }}'::date
   or (select max(month_start) from snapshot) <> e.as_of_month
   or exists (
       select 1 from snapshot
       where is_month_closed = (month_start = e.as_of_month)
   )
   or (select count(distinct as_of_date) from snapshot) <> 1
