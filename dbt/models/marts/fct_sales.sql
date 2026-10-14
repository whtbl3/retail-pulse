{{ config(
    materialized='incremental',
    unique_key=['transaction_id', 'line_number']
) }}

with items as (
    select
        i.transaction_id,
        i.line_number,
        i.product_id,
        i.promotion_id,
        i.quantity,
        i.regular_price,
        coalesce(i.coupon_amount, 0) as coupon_amount,
        t.store_id,
        t.employee_id,
        t.payment_method_id,
        t.transaction_ts,
        -- A row's "freshness" mark: the later of the line item and the invoice
        greatest(i.updated_at, t.updated_at) as source_updated_at
    from {{ ref('stg_sales_transaction_item') }} i
    join {{ ref('stg_sales_transaction') }} t using (transaction_id)
    {% if is_incremental() %}
    -- >= so late rows with exactly the boundary updated_at are not missed; unique_key prevents duplicates
    where greatest(i.updated_at, t.updated_at) >= (select max(source_updated_at) from {{ this }})
    {% endif %}
),

joined as (
    select
        it.*,
        -- No match gives null from the left join; COALESCE in the final select assigns -2
        s.store_key,
        pm.payment_method_key,
        e.employee_key,
        p.product_key,
        p.unit_cost,
        pr.promotion_key,
        pr.promotion_type,
        pr.promotion_amount
    from items it
    left join {{ ref('dim_store') }} s
        on it.store_id = s.store_id
    left join {{ ref('dim_payment_method') }} pm
        on it.payment_method_id = pm.payment_method_id
    left join {{ ref('dim_promotion') }} pr
        on it.promotion_id = pr.promotion_id
    -- Half-open range join on the original transaction_ts (UTC): each transaction matches exactly one version
    left join {{ ref('dim_product') }} p
        on  it.product_id = p.product_id
        and it.transaction_ts >= p.valid_from
        and it.transaction_ts <  p.valid_to
    left join {{ ref('dim_employee') }} e
        on  it.employee_id = e.employee_id
        and it.transaction_ts >= e.valid_from
        and it.transaction_ts <  e.valid_to
),

measures as (
    select
        *,
        quantity * regular_price as gross_amount,
        case promotion_type
            when 'percentage'   then quantity * regular_price * promotion_amount / 100
            when 'fixed_amount' then quantity * least(promotion_amount, regular_price)
            else 0                                   -- -1, -2 and anything else: no discount
        end as discount_amount
    from joined
),

local_ts as (
    select
        *,
        -- Only the date/time keys use local time; the original transaction_ts is unchanged
        convert_timezone('{{ var("local_tz") }}', transaction_ts) as local_transaction_ts
    from measures
),

-- Date/time keys are computed from local time, then looked up in dim_date and dim_time like other dimensions,
-- so a date/time missing from the dimension falls back to -2 (instead of failing the relationships test)
timed as (
    select
        l.*,
        d.date_key as dim_date_key,
        t.time_key as dim_time_key
    from local_ts l
    left join {{ ref('dim_date') }} d
        on d.date_key = to_number(to_char(l.local_transaction_ts::date, 'YYYYMMDD'))
    left join {{ ref('dim_time') }} t
        on t.time_key = hour(l.local_transaction_ts) * 100 + minute(l.local_transaction_ts)
)

select
    coalesce(dim_date_key, -2)                                        as date_key,
    coalesce(dim_time_key, -2)                                        as time_key,
    coalesce(product_key, -2)                                         as product_key,
    coalesce(store_key, -2)                                           as store_key,
    coalesce(employee_key, -2)                                        as employee_key,
    coalesce(payment_method_key, -2)                                  as payment_method_key,
    case
        when promotion_id is null then -1                             -- no promotion
        else coalesce(promotion_key, -2)                              -- has an ID, but it is not in the dimension yet
    end                                                               as promotion_key,
    transaction_id,
    line_number,
    transaction_ts,
    quantity,
    regular_price,
    unit_cost,
    gross_amount,
    discount_amount,
    coupon_amount,
    gross_amount - discount_amount - coupon_amount                         as net_amount,
    quantity * unit_cost                                                   as cost_amount,
    gross_amount - discount_amount - coupon_amount - quantity * unit_cost  as gross_profit,
    source_updated_at
from timed
