"""Regression coverage for source parsing, diff fidelity, deletions, and CI policy."""

from unittest.mock import Mock

import pytest

from dbt_reviewer.checks import ModelContext
from dbt_reviewer.context import RepositoryContext
from dbt_reviewer.diff import parse_diff
from dbt_reviewer.models import Evidence, Finding
from dbt_reviewer.review import review
from tests.helpers import model, patch


@pytest.mark.parametrize("context", [0, 3])
def test_wrong_checkout_rejected_before_any_provider_call(tmp_path, context):
    before = "select id\nfrom {{ ref('orders') }}\n"
    after = "select id\nfrom raw.orders\n"
    model(tmp_path, before)
    provider = Mock()
    with pytest.raises(ValueError, match="does not match current model"):
        review(tmp_path, parse_diff(patch(before, after, context)), semantic=provider)
    provider.review.assert_not_called()


@pytest.mark.parametrize("context", [0, 3])
def test_deletion_only_reaches_semantic_review_with_valid_surviving_anchor(tmp_path, context):
    lines = [
        "select o.id\n",
        "from {{ ref('orders') }} o\n",
        "join {{ ref('payments') }} p\n",
        "on o.id = p.order_id\n",
    ]
    before = "".join(lines) + "where p.amount > 0\n"
    after = "".join(lines)
    model(tmp_path, after)
    diff = patch(before, after, context)
    changed = parse_diff(diff)[0]
    assert not changed.added_lines
    payload = RepositoryContext(tmp_path).build(ModelContext(changed, after), diff, [])
    assert payload["changed_lines"]
    assert all(1 <= n <= len(lines) for n in payload["changed_lines"])
    finding = Finding(
        check_id="JOIN_FANOUT",
        source="semantic",
        file=changed.path,
        line=payload["changed_lines"][0],
        severity="warning",
        message="Deletion affects grain",
        confidence="high",
        evidence=[
            Evidence(
                status="confirmed_fact",
                statement="Current SQL",
                reference={"file": changed.path, "line": 1, "end_line": 1},
            )
        ],
    )
    provider = Mock()
    provider.review.return_value = [finding]
    assert finding in review(tmp_path, [changed], semantic=provider, diff_text=diff)
    provider.review.assert_called_once()


def test_all_changed_models_are_reviewed_without_run_budget(tmp_path):
    from dbt_reviewer.models import ChangedFile
    from tests.helpers import write

    changed = []
    for i in range(6):
        name = f"models/model_{i}.sql"
        write(tmp_path, name, "select 1 as id\n")
        changed.append(ChangedFile(name, frozenset({1})))
    provider = Mock()
    provider.review.return_value = []
    diagnostics = []
    assert review(tmp_path, changed, semantic=provider, diagnostics=diagnostics) == []
    assert provider.review.call_count == 6
    assert not diagnostics
