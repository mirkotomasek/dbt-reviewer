-- Adapted from jaffle_shop_duckdb: explicit columns and total payment only.
with order_payments as (
    select order_id, sum(amount) as amount
    from {{ ref('stg_payments') }}
    group by order_id
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    order_payments.amount
from {{ ref('stg_orders') }} as orders
left join order_payments
    on orders.order_id = order_payments.order_id
