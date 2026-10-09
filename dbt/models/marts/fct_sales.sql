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
        -- Mốc "mới" của một dòng: lấy giá trị lớn hơn của dòng chi tiết và hóa đơn
        greatest(i.updated_at, t.updated_at) as source_updated_at
    from {{ ref('stg_sales_transaction_item') }} i
    join {{ ref('stg_sales_transaction') }} t using (transaction_id)
    {% if is_incremental() %}
    -- >= để không bỏ sót dòng đến muộn có đúng updated_at ở biên; unique_key chặn trùng
    where greatest(i.updated_at, t.updated_at) >= (select max(source_updated_at) from {{ this }})
    {% endif %}
),

joined as (
    select
        it.*,
        -- Không khớp thì left join ra rỗng, COALESCE ở select cuối gán -2
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
    -- Join khoảng nửa mở bằng transaction_ts gốc (UTC): mỗi giao dịch khớp đúng một phiên bản
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
            else 0                                   -- -1, -2 và mọi giá trị khác: không giảm
        end as discount_amount
    from joined
),

local_ts as (
    select
        *,
        -- Chỉ khóa ngày/giờ dùng giờ địa phương; transaction_ts gốc giữ nguyên
        convert_timezone('{{ var("local_tz") }}', transaction_ts) as local_transaction_ts
    from measures
),

-- Khóa ngày/giờ tính từ giờ địa phương rồi tra lại dim_date, dim_time như các dimension khác,
-- nên ngày/giờ không có trong dimension rơi về -2 (không làm fail test relationships)
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
        when promotion_id is null then -1                             -- không có khuyến mãi
        else coalesce(promotion_key, -2)                              -- có mã nhưng dimension chưa có
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
