-- fct_sales at the same grain, plus the dimension attributes the dashboard slices by.
-- The semantic layer (models/semantic/) defines every metric on this one model, because the Preset
-- sync turns each metric into a single expression on a single dataset and cannot use joins.
-- Joins use the fact's surrogate keys, so product attributes are the version valid at the time of sale.
-- Every fact key has a matching dimension row (-1 and -2 members included), so inner joins keep every row.
select
    f.transaction_id,
    f.line_number,
    f.transaction_ts,
    d.full_date,
    d.year,
    d.month,
    d.month_name,
    d.day_name,
    d.is_weekend,
    s.store_name,
    p.product_name,
    p.category_name,
    p.brand_name,
    pr.promotion_label,
    pr.promotion_type,
    pm.payment_method_name,
    f.quantity,
    f.gross_amount,
    f.discount_amount,
    f.coupon_amount,
    f.net_amount,
    f.cost_amount,
    f.gross_profit
from {{ ref('fct_sales') }} f
join {{ ref('dim_date') }} d             on f.date_key = d.date_key
join {{ ref('dim_store') }} s            on f.store_key = s.store_key
join {{ ref('dim_product') }} p          on f.product_key = p.product_key
join {{ ref('dim_promotion') }} pr       on f.promotion_key = pr.promotion_key
join {{ ref('dim_payment_method') }} pm  on f.payment_method_key = pm.payment_method_key
