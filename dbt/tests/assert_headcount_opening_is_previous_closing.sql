-- Spec 004, AC2: each month's opening headcount is the previous month's closing headcount at the same
-- store. (The identity closing = opening + flows is a generic test in marts/___models.yml.)
select *
from (
    select
        store_id,
        month_start,
        opening_headcount,
        lag(closing_headcount) over (partition by store_id order by month_start) as previous_closing
    from {{ ref('fct_store_headcount_monthly') }}
)
where previous_closing is not null
  and opening_headcount <> previous_closing
