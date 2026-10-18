"""Verify the external engine's integration, source mapping, and configuration."""

from unittest.mock import Mock

import pytest

from dbt_reviewer.checks import HardcodedRelation
from dbt_reviewer.lint import SQLFluffCheck
from dbt_reviewer.models import ChangedFile, ModelContext
from dbt_reviewer.sql import masked_sql


def context(sql, lines=None):
    return ModelContext(
        ChangedFile("models/a.sql", frozenset(lines or range(1, len(sql.splitlines()) + 1))), sql
    )


def test_missing_condition_after_pure_deletion_uses_surviving_join_line():
    sql = "select a.id\nfrom a\njoin b\n"
    ctx = ModelContext(ChangedFile("models/a.sql", frozenset(), frozenset({4})), sql)
    assert [(f.check_id, f.line) for f in SQLFluffCheck().run(ctx)] == [("SQLFLUFF:AM08", 3)]


def test_resolved_final_cte_wildcard_is_allowed_by_sqlfluff():
    sql = "with final as (select id from orders) select * from final"
    assert SQLFluffCheck().run(context(sql)) == []


def test_native_noqa_and_exclusions_are_respected():
    check = SQLFluffCheck(rules="AM04,CV05", exclude_rules="CV05")
    assert check.run(context("select * from orders where id = null -- noqa: AM04")) == []


def test_ast_policy_finds_qualified_relations_in_comma_joins():
    findings = HardcodedRelation().run(context("select a.id from raw.a a, raw.b b"))
    assert len(findings) == 2


def test_jinja_masking_preserves_sql_literals_comments_and_line_positions():
    sql = "select $$ {# literal #} {{ ref('ignored') }} $$ as label\n{# real comment #}\nfrom {{ ref('real') }}\n"
    masked, spans = masked_sql(sql)
    assert len(masked) == len(sql)
    assert "$$ {# literal #} {{ ref('ignored') }} $$" in masked
    assert masked.count("\n") == sql.count("\n")
    assert len(spans) == 2


def test_sqlfluff_real_rule_and_safe_raw_templater(monkeypatch):
    from sqlfluff.core.templaters.jinja import JinjaTemplater

    monkeypatch.setattr(
        JinjaTemplater, "process", Mock(side_effect=AssertionError("must not execute Jinja"))
    )
    sql = "{% do arbitrary_repository_code() %}\nselect * from {{ ref('orders') }}\n"
    check = SQLFluffCheck("snowflake", "AM04")
    findings = check.run(context(sql))
    assert [f.check_id for f in findings] == ["SELECT_STAR"]
    assert findings[0].line == 2


def test_sqlfluff_invalid_dialect_is_actionable():
    with pytest.raises(ValueError, match="Invalid SQLFluff configuration"):
        SQLFluffCheck("does_not_exist").run(context("select 1"))
