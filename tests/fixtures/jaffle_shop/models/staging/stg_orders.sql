-- Adapted from jaffle_shop_duckdb: simplified projection; raw seeds omitted.
select
    id as order_id,
    user_id as customer_id,
    order_date,
    status
from {{ ref('raw_orders') }}
