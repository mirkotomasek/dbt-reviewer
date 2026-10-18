"""Direct-parent SQL and schema context without a dbt manifest."""

import json

import pytest

from dbt_reviewer.context import ContextError, RepositoryContext
from dbt_reviewer.models import ChangedFile, ModelContext
from tests.helpers import SQL, make_diff, setup_repo, write
from tests.helpers import write as put


def test_context_has_only_relevant_models_and_schema_declarations(tmp_path):
    ctx = setup_repo(tmp_path)
    write(tmp_path, "models/unrelated.sql", "SECRET_UNRELATED_SQL")
    payload = RepositoryContext(tmp_path).build(ctx, make_diff(), [])
    assert payload["changed_lines"] == [3, 4]
    assert "+left join" in payload["diff"]
    assert payload["sql"] == SQL
    upstream = {n["metadata"]["name"]: n for n in payload["direct_upstream"]}
    assert set(upstream) == {"stg_orders", "stg_payments"}
    assert "payment_id" in upstream["stg_payments"]["sql"]
    assert upstream["stg_orders"]["yaml"][0]["declaration"]["columns"][0]["tests"] == [
        "unique",
        "not_null",
    ]
    assert "SECRET_UNRELATED_SQL" not in json.dumps(payload)


def test_bad_yaml_is_uncertain_not_fatal(tmp_path):
    ctx = setup_repo(tmp_path)
    write(tmp_path, "models/bad.yml", "models: [")
    payload = RepositoryContext(tmp_path).build(ctx, make_diff(), [])
    assert any("Could not read model YAML" in n for n in payload["limitations"])


def test_ref_discovery_skips_comments_and_handles_package_refs():
    sql = "-- {{ ref('ignored') }}\nselect * from {{ ref('package', 'orders') }} /* {{ ref('also_ignored') }} */"
    assert RepositoryContext.ref_names(sql) == ["orders"]


def test_ambiguous_or_missing_parent_is_explicit(tmp_path):
    ctx = setup_repo(tmp_path)
    write(tmp_path, "models/duplicate/stg_payments.sql", "select 1")
    payload = RepositoryContext(tmp_path).build(ctx, make_diff(), [])
    assert len(payload["direct_upstream"]) == 1
    assert any("stg_payments is missing or ambiguous" in n for n in payload["limitations"])


def test_context_bounds_and_path_safety(tmp_path, monkeypatch):
    ctx = setup_repo(tmp_path)
    repository = RepositoryContext(tmp_path)
    with pytest.raises(ContextError, match="escapes"):
        repository.read("../outside.sql")
    with pytest.raises(ContextError, match="exceeds"):
        repository.read("models/orders.sql", limit=2)
    monkeypatch.setattr("dbt_reviewer.context.MAX_PAYLOAD_CHARS", 10)
    with pytest.raises(ContextError, match="payload budget"):
        repository.build(ctx, make_diff(), [])


def test_other_files_diff_is_not_sent(tmp_path):
    ctx = setup_repo(tmp_path)
    unrelated = (
        "--- a/models/secret.sql\n+++ b/models/secret.sql\n@@ -1 +1 @@\n-old\n+SECRET_DIFF\n"
    )
    payload = RepositoryContext(tmp_path).build(ctx, make_diff() + unrelated, [])
    assert "SECRET_DIFF" not in payload["diff"]


def test_model_context_does_not_depend_on_previously_reviewed_model(tmp_path):
    a = ModelContext(
        ChangedFile("models/a.sql", frozenset({1})), "select id from {{ ref('missing') }}\n"
    )
    b = ModelContext(ChangedFile("models/b.sql", frozenset({1})), "select 1 as id\n")
    put(tmp_path, a.changed_file.path, a.sql)
    put(tmp_path, b.changed_file.path, b.sql)
    repo = RepositoryContext(tmp_path)
    assert any("missing" in n for n in repo.build(a, "", [])["limitations"])
    after = repo.build(b, "", [])
    alone = RepositoryContext(tmp_path).build(b, "", [])
    assert after == alone
    assert repo.build(a, "", []) == RepositoryContext(tmp_path).build(a, "", [])
