# Minimal Jaffle Shop fixture

Adapted from [dbt-labs/jaffle_shop_duckdb, branch `duckdb`](https://github.com/dbt-labs/jaffle_shop_duckdb/tree/duckdb)
for reviewer evaluation purposes, under the included Apache 2.0 [license](LICENSE).
SQL projections and YAML declarations are shortened; the order/payment identifier
mappings, cents-to-dollars conversion, and unique key declarations are retained.
`legacy.sql` is an evaluation-only addition with a pre-existing wildcard.

Only reviewer context is included. Raw seed references are intentionally unresolved;
there are no data, profiles, packages, or database requirements. Do not run dbt here.
A unique `payment_id` is declared; payment `order_id` uniqueness is not established.
This supports a conditional fanout risk, not a claim about actual warehouse rows.
