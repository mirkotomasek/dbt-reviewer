-- Existing wildcard used only to evaluate changed-line precision.
select * from {{ ref('stg_orders') }}
