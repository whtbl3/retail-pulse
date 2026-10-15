-- Periodic snapshot fact (spec 004): one row per store per calendar month, from date_start (January 2020)
-- to the month of the as-of day, including store-months with no staff or no sales.
--
-- Headcount comes from int_employee_daily_store (state at the end of each local day):
--   opening = employed on the day before the month starts, closing = employed on the month's last day
--   (the as-of day for the current month); joiners, leavers and transfers are day-to-day changes inside
--   the month, so closing = opening + joiners + transfers_in - leavers - transfers_out by construction.
-- Headcount is semi-additive: sum it across stores, never across months.
-- Revenue per employee is a semantic-layer metric (models/semantic/headcount.yml), not a column here.
-- store_name and month_start are on the fact so Preset and MetricFlow can read it without joins.

with as_of as (
    -- The last day the daily table was built for, so this model and its parent agree even when a build
    -- runs past local midnight
    select coalesce(max(calendar_date), {{ headcount_as_of() }}) as as_of_date
    from {{ ref('int_employee_daily_store') }}
),

months as (
    select
        m.month_start,
        least(last_day(m.month_start), a.as_of_date) as closing_date,
        last_day(m.month_start) < a.as_of_date      as is_month_closed,
        a.as_of_date
    from (
        select dateadd(
            month, row_number() over (order by seq4()) - 1, '{{ var("date_start") }}'::date
        ) as month_start
        from table(generator(rowcount => {{ (var('date_days') // 28) + 1 }}))
    ) m
    cross join as_of a
    where m.month_start <= a.as_of_date
),

stores as (
    select store_key, store_id, store_name
    from {{ ref('dim_store') }}
    where store_key <> -2
),

daily as (
    select * from {{ ref('int_employee_daily_store') }}
),

opening as (
    select m.month_start, d.store_id, count(*) as headcount
    from months m
    join daily d on d.calendar_date = dateadd(day, -1, m.month_start) and d.is_employed
    group by 1, 2
),

closing as (
    select m.month_start, d.store_id, count(*) as headcount
    from months m
    join daily d on d.calendar_date = m.closing_date and d.is_employed
    group by 1, 2
),

-- One row per movement, at the store it affects
movements as (
    select date_trunc('month', calendar_date) as month_start, store_id, 'joiner' as movement
    from daily
    where is_employed and not prev_is_employed

    union all

    select date_trunc('month', calendar_date), prev_store_id, 'leaver'
    from daily
    where prev_is_employed and not is_employed

    union all

    select date_trunc('month', calendar_date), store_id, 'transfer_in'
    from daily
    where prev_is_employed and is_employed and store_id <> prev_store_id

    union all

    select date_trunc('month', calendar_date), prev_store_id, 'transfer_out'
    from daily
    where prev_is_employed and is_employed and store_id <> prev_store_id
),

movement_counts as (
    select
        month_start,
        store_id,
        count_if(movement = 'joiner')       as joiners,
        count_if(movement = 'leaver')       as leavers,
        count_if(movement = 'transfer_in')  as transfers_in,
        count_if(movement = 'transfer_out') as transfers_out
    from movements
    group by 1, 2
),

-- fct_sales holds completed sales only; date_key is the local date
revenue as (
    select
        date_trunc('month', d.full_date) as month_start,
        s.store_id,
        sum(f.net_amount)                as net_revenue
    from {{ ref('fct_sales') }} f
    join {{ ref('dim_store') }} s on f.store_key = s.store_key
    join {{ ref('dim_date') }} d  on f.date_key = d.date_key
    group by 1, 2
)

select
    s.store_key,
    s.store_id,
    s.store_name,
    m.month_start,
    to_number(to_char(m.month_start, 'YYYYMMDD'))                     as month_start_date_key,
    coalesce(o.headcount, 0)                                          as opening_headcount,
    coalesce(c.headcount, 0)                                          as closing_headcount,
    coalesce(mc.joiners, 0)                                           as joiners,
    coalesce(mc.leavers, 0)                                           as leavers,
    coalesce(mc.transfers_in, 0)                                      as transfers_in,
    coalesce(mc.transfers_out, 0)                                     as transfers_out,
    ((coalesce(o.headcount, 0) + coalesce(c.headcount, 0)) / 2)::number(10, 1) as average_headcount,
    coalesce(r.net_revenue, 0)                                        as net_revenue,
    m.is_month_closed,
    m.as_of_date
from stores s
cross join months m
left join opening o         on o.store_id = s.store_id  and o.month_start = m.month_start
left join closing c         on c.store_id = s.store_id  and c.month_start = m.month_start
left join movement_counts mc on mc.store_id = s.store_id and mc.month_start = m.month_start
left join revenue r         on r.store_id = s.store_id  and r.month_start = m.month_start
