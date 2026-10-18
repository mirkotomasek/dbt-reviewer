import difflib
import io
import json

import pytest

from dbt_reviewer.checks import HardcodedRelation, ModelContext
from dbt_reviewer.cli import main
from dbt_reviewer.context import RepositoryContext
from dbt_reviewer.models import ChangedFile
from dbt_reviewer.review import review


def context(sql, lines=None):
    return ModelContext(
        ChangedFile(
            "models/orders.sql",
            frozenset(lines if lines is not None else range(1, len(sql.splitlines()) + 1)),
        ),
        sql,
    )


@pytest.mark.parametrize(
    "relation",
    ["raw.orders", "raw.jaffle_shop.orders", '"raw"."orders"', "`project.dataset.orders`"],
)
def test_hardcoded_relation(relation):
    dialect = "bigquery" if relation.startswith("`") else "duckdb"
    findings = HardcodedRelation(dialect).run(context(f"select order_id\nfrom {relation}\n"))
    assert len(findings) == 1
    assert (findings[0].check_id, findings[0].severity, findings[0].line) == ("D001", "error", 2)


@pytest.mark.parametrize(
    "sql",
    [
        "select id from {{ ref('orders') }}",
        "select id from {{ source('raw', 'orders') }}",
        "with final as (select 1 as id) select * from final",
        "select 'from raw.orders' as description -- join raw.payments\n",
        "/* from raw.orders */ select 1",
        "{# from raw.orders #} select 1",
        "{% set x = 'from raw.orders' %} select 1",
        "select * from generate_series(1, 5)",
        "select * from raw.table_function(1)",
    ],
)
def test_hardcoded_relation_clean(sql):
    assert HardcodedRelation().run(context(sql)) == []


def test_hardcoded_relation_only_reports_changed_reference():
    sql = "select id,\n amount\nfrom raw.orders\njoin raw.payments using (id)\n"
    assert HardcodedRelation().run(context(sql, {2})) == []
    findings = HardcodedRelation().run(context(sql, {4}))
    assert len(findings) == 1
    assert "raw.payments" in findings[0].message


def test_multiline_relation_anchor():
    findings = HardcodedRelation().run(context("select id from\n raw.\n orders", {3}))
    assert findings[0].line == 3


def write_model(repo, sql):
    path = repo / "models/orders.sql"
    path.parent.mkdir(exist_ok=True)
    path.write_text(sql, encoding="utf-8")
    return path


def test_review_reads_full_model_and_deduplicates(tmp_path):
    write_model(tmp_path, "select *\nfrom raw.orders\n")
    changed = ChangedFile("models/orders.sql", frozenset({2}))
    findings = review(tmp_path, [changed, changed])
    assert [f.check_id for f in findings] == ["D001"]
    assert all(f.line == 2 for f in findings)


def test_missing_current_model_errors(tmp_path):
    with pytest.raises(ValueError, match="Cannot read current model"):
        review(tmp_path, [ChangedFile("models/missing.sql", frozenset({1}))])


def test_symlink_escape_errors(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/out.sql").symlink_to(tmp_path.parent / "outside.sql")
    with pytest.raises(ValueError, match="escapes repository"):
        review(tmp_path, [ChangedFile("models/out.sql", frozenset({1}))])


def test_outdated_line_locations_error(tmp_path):
    write_model(tmp_path, "select 1\n")
    with pytest.raises(ValueError, match="apply the diff"):
        review(tmp_path, [ChangedFile("models/orders.sql", frozenset({5}))])


def test_clean_diff_does_not_report_existing_issues(tmp_path, monkeypatch, capsys):
    before = "select *\nfrom raw.orders\nwhere id > 1\n"
    after = "select *\nfrom raw.orders\nwhere id > 2\n"
    write_model(tmp_path, after)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="a/models/orders.sql",
            tofile="b/models/orders.sql",
        )
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(diff))
    assert main(["--repo", str(tmp_path), "--format", "json", "--no-llm"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize(
    "literal",
    [
        "$$from raw.orders$$",
        "$tag$join raw.orders$tag$",
        "'from raw.orders'",
        "'it''s from raw.orders'",
        '$$ {{ ref("ghost") }} $$',
    ],
)
def test_sqlglot_preserves_sql_literals(literal):
    sql = f"select {literal} as label\n"
    assert HardcodedRelation().run(context(sql)) == []
    assert RepositoryContext.ref_names(sql) == []


@pytest.mark.parametrize(
    "expression",
    [
        "extract(year from o.created_at)",
        "o.id is distinct from p.id",
    ],
)
def test_expression_from_is_not_a_relation(expression):
    sql = f"select {expression} as value from {{{{ ref('orders') }}}} o\n"
    assert (
        HardcodedRelation().run(ModelContext(ChangedFile("models/orders.sql", frozenset({1})), sql))
        == []
    )


def test_real_nested_relations_still_report():
    sql = "select extract(year from o.created_at), (select max(p.amount) from raw.payments p) from raw.orders o"
    result = HardcodedRelation().run(
        ModelContext(ChangedFile("models/orders.sql", frozenset({1})), sql)
    )
    assert len(result) == 2
    assert all("o.created_at" not in f.message for f in result)
