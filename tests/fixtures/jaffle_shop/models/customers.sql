-- Adapted from jaffle_shop_duckdb: only customer order metrics retained.
select
    customer_id,
    count(order_id) as number_of_orders,
    min(order_date) as first_order,
    max(order_date) as most_recent_order
from {{ ref('stg_orders') }}
group by customer_id
