"""Small repository and provider-response builders shared by behavior tests."""

import difflib

from dbt_reviewer.models import ChangedFile, Evidence, Finding, ModelContext

SQL = """select orders.order_id, payments.amount
from {{ ref('stg_orders') }} orders
left join {{ ref('stg_payments') }} payments
    on orders.order_id = payments.order_id
"""


def write(repo, path, contents):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


def setup_repo(repo):
    write(repo, "models/orders.sql", SQL)
    write(
        repo,
        "models/staging/stg_orders.sql",
        "select id as order_id from {{ source('shop', 'orders') }}",
    )
    write(
        repo,
        "models/staging/stg_payments.sql",
        "select id as payment_id, order_id, amount from {{ source('shop', 'payments') }}",
    )
    write(
        repo,
        "models/schema.yml",
        """version: 2
models:
  - name: stg_orders
    columns:
      - name: order_id
        tests: [unique, not_null]
  - name: stg_payments
    columns:
      - name: payment_id
        data_tests: [unique, not_null]
      - name: order_id
        data_tests: [not_null]
  - name: orders
    description: One row per order
""",
    )
    return ModelContext(ChangedFile("models/orders.sql", frozenset({3, 4})), SQL)


def make_diff():
    return "".join(
        difflib.unified_diff(
            SQL.splitlines(True)[:2],
            SQL.splitlines(True),
            fromfile="a/models/orders.sql",
            tofile="b/models/orders.sql",
        )
    )


def issue(**updates):
    return (
        dict(
            check_id="JOIN_FANOUT",
            severity="warning",
            confidence="high",
            line=3,
            message="Joining payment-grain rows may multiply order rows.",
            suggestion="Aggregate payments to order_id before joining.",
            evidence=[
                dict(
                    status="confirmed_fact",
                    statement="Payments retain payment_id and order_id without aggregation.",
                    reference={"file": "models/staging/stg_payments.sql", "line": 1, "end_line": 1},
                )
            ],
        )
        | updates
    )


def semantic_finding(**updates):
    return Finding(
        **(
            {
                "check_id": "JOIN_FANOUT",
                "severity": "warning",
                "confidence": "high",
                "file": "models/orders.sql",
                "line": 3,
                "source": "semantic",
                "message": "Joining payments can multiply orders.",
                "suggestion": "Aggregate payments by order_id first.",
                "evidence": [
                    Evidence(
                        status="confirmed_fact",
                        statement="Payments retain order_id.",
                        reference={"file": "models/payments.sql", "line": 1, "end_line": 2},
                    ),
                    Evidence(
                        status="high_confidence_risk",
                        statement="Orders may repeat.",
                        reference={"file": "models/orders.sql", "line": 3, "end_line": 3},
                    ),
                ],
            }
            | updates
        )
    )


def patch(before, after, context=3):
    return "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="a/models/orders.sql",
            tofile="b/models/orders.sql",
            n=context,
        )
    )


def model(repo, sql):
    (repo / "models").mkdir(exist_ok=True)
    (repo / "models/orders.sql").write_text(sql)
