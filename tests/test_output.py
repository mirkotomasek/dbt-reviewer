"""Human output and semantic trust boundaries share the same detailed findings."""

import json

import pytest

from dbt_reviewer.models import Finding
from dbt_reviewer.output import render_findings
from dbt_reviewer.review import deduplicate
from tests.helpers import semantic_finding


def test_concise_verbose_and_json_preserve_their_intended_detail():
    finding = semantic_finding()
    concise = render_findings([finding], "text")
    assert concise.startswith(
        "1 finding (1 warning)\n\nWARNING JOIN_FANOUT models/orders.sql:3 [high confidence]"
    )
    assert "Evidence: Payments retain order_id." in concise
    assert "Fix: Aggregate payments" in concise
    assert "confirmed_fact" not in concise and "Orders may repeat" not in concise
    detailed = render_findings([finding], "text", verbose=True)
    assert "[confirmed_fact] Payments retain order_id. (models/payments.sql:1-2)" in detailed
    assert "[high_confidence_risk] Orders may repeat." in detailed
    assert json.loads(render_findings([finding], "json"))[0] == finding.model_dump()
    assert render_findings([finding], "json", verbose=True) == render_findings([finding], "json")
    assert render_findings([], "text", verbose=True) == "No findings."


def test_deterministic_root_cause_wins_but_distinct_join_risk_survives():
    star = Finding(
        check_id="SELECT_STAR",
        engine_rule="SQLFLUFF:AM04",
        severity="warning",
        file="models/orders.sql",
        line=1,
        source="deterministic",
        message="Implicit schema",
    )
    overlap = semantic_finding(
        check_id="DBT_MODEL", line=1, message="SELECT * exposes all upstream columns."
    )
    join = semantic_finding(message="The join can multiply rows even with SELECT *.")
    assert deduplicate([star, overlap, join]) == [star, join]
    other_file = overlap.model_copy(update={"file": "models/other.sql"})
    assert deduplicate([star, other_file]) == [star, other_file]


@pytest.mark.parametrize("projection", ["*", "orders.*"])
def test_wildcard_wording_covers_qualified_and_unqualified_projections(projection):
    from dbt_reviewer.lint import SQLFluffCheck
    from dbt_reviewer.models import ChangedFile, ModelContext

    sql = f"select {projection} from {{{{ ref('orders') }}}} orders\n"
    context = ModelContext(ChangedFile("models/example.sql", frozenset({1})), sql)
    finding = next(f for f in SQLFluffCheck().run(context) if f.check_id == "SELECT_STAR")
    assert finding.message.startswith("Wildcard projection makes the output schema implicit")
    assert "SELECT *" not in finding.message
    assert finding.engine_rule == "SQLFLUFF:AM04"
