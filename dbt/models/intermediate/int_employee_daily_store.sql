-- One row per employee per local calendar day: the employee's state at the END of that day (spec 004).
-- Days run from the day before date_start (the opening day of the first snapshot month) to the as-of
-- day (today in local time). fct_store_headcount_monthly counts movements by comparing each day with the
-- day before, so closing = opening + joiners + transfers in - leavers - transfers out always holds.
--
-- - Employed at the end of day d: start_date <= d and end_date is null or after d. The last working day
--   (end_date) is therefore not employed at its end: that day is when the employee leaves.
-- - Store at the end of day d: the int_employee_scd2 version valid at the instant day d ends (local
--   midnight), compared on the timestamps as in the point-in-time joins of fct_sales. Before the first
--   recorded transfer the first version applies (valid from 1900-01-01).

with days as (
    select
        dateadd(
            day,
            row_number() over (order by seq4()) - 1,
            dateadd(day, -1, '{{ var("date_start") }}'::date)
        ) as calendar_date
    from table(generator(rowcount => {{ var('date_days') + 1 }}))
),

day_ends as (
    select
        calendar_date,
        timestamp_tz_from_parts(
            year(dateadd(day, 1, calendar_date)),
            month(dateadd(day, 1, calendar_date)),
            day(dateadd(day, 1, calendar_date)),
            0, 0, 0, 0,
            '{{ var("local_tz") }}'
        ) as day_end_ts
    from days
    where calendar_date <= {{ headcount_as_of() }}
),

-- start_date and end_date are Type 1, the same on every version
employees as (
    select distinct employee_id, start_date, end_date
    from {{ ref('int_employee_scd2') }}
),

states as (
    select
        e.employee_id,
        d.calendar_date,
        coalesce(
            e.start_date <= d.calendar_date
            and (e.end_date is null or e.end_date > d.calendar_date),
            false
        ) as is_employed,
        v.store_id
    from employees e
    cross join day_ends d
    join {{ ref('int_employee_scd2') }} v
        on  v.employee_id = e.employee_id
        and d.day_end_ts >= v.valid_from
        and d.day_end_ts <  v.valid_to
)

select
    employee_id,
    calendar_date,
    is_employed,
    store_id,
    -- Null on the first day: there is no day before it to compare with
    lag(is_employed) over (partition by employee_id order by calendar_date) as prev_is_employed,
    lag(store_id) over (partition by employee_id order by calendar_date)    as prev_store_id
from states
