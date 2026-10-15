-- Spec 004, AC3: closing headcount recomputed straight from int_employee_scd2, without the daily
-- table: employees employed after the closing day (start_date <= day < end_date or no end_date),
-- counted at the store of the version valid when that local day ends.
with snapshot as (
    select * from {{ ref('fct_store_headcount_monthly') }}
),

closing_days as (
    select distinct
        month_start,
        least(last_day(month_start), as_of_date) as closing_date
    from snapshot
),

recomputed as (
    select c.month_start, v.store_id, count(distinct v.employee_id) as headcount
    from closing_days c
    join {{ ref('int_employee_scd2') }} v
        on  v.start_date <= c.closing_date
        and (v.end_date is null or v.end_date > c.closing_date)
        and convert_timezone('{{ var("local_tz") }}', v.valid_from)::date <= c.closing_date
        and convert_timezone('{{ var("local_tz") }}', v.valid_to)::date   >  c.closing_date
    group by 1, 2
)

select s.store_id, s.month_start, s.closing_headcount, coalesce(r.headcount, 0) as recomputed
from snapshot s
left join recomputed r on r.store_id = s.store_id and r.month_start = s.month_start
where s.closing_headcount <> coalesce(r.headcount, 0)
