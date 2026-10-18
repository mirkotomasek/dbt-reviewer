"""Reproduce the audit failures through the CLI and repository-context boundary."""

import difflib
import json
import subprocess
from unittest.mock import Mock

import pytest

from dbt_reviewer.cli import main
from dbt_reviewer.context import RepositoryContext
from dbt_reviewer.diff import model_paths, parse_diff, previous_sql
from dbt_reviewer.models import ModelContext
from dbt_reviewer.review import review


@pytest.fixture(autouse=True)
def isolate_provider_environment(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "DBT_REVIEW_MODEL",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def prepare(root, before, after, path="models/orders.sql", context=3):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(after, encoding="utf-8")
    patch = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
            n=context,
        )
    )
    patchfile = root / "change.diff"
    patchfile.write_text(patch, encoding="utf-8")
    return patchfile, patch


@pytest.mark.parametrize(
    "config",
    [
        "{{ config(materialized='table') }}",
        "{{ config(meta={'owner': {'name': 'analytics'}}) }}",
        '{{ config(meta={"description": "contains }} text"}) }}',
        "{{- config(materialized='table') -}}",
    ],
)
def test_valid_dbt_config_does_not_hide_changed_sql(tmp_path, capsys, config):
    before = config + "\nselect id from {{ ref('orders') }}\n"
    after = config + "\nselect * from raw.orders\n"
    patchfile, _ = prepare(tmp_path, before, after)
    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--diff",
                str(patchfile),
                "--no-llm",
                "--format",
                "json",
                "--fail-on",
                "error",
            ]
        )
        == 1
    )
    result = capsys.readouterr()
    assert not result.err
    assert {f["check_id"] for f in json.loads(result.out)} == {"D001", "SELECT_STAR"}


@pytest.mark.parametrize("filename", ["café.sql", "has space.sql", "with\ttab.sql"])
def test_real_git_paths_reach_checks_and_semantic_context(tmp_path, monkeypatch, capsys, filename):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = "models/" + filename
    sql = "select * from raw.orders\n"
    prepare(tmp_path, "", sql, path)
    subprocess.run(["git", "-C", str(tmp_path), "add", "models"], check=True)
    patch = subprocess.check_output(["git", "-C", str(tmp_path), "diff", "--cached"], text=True)
    changed = parse_diff(patch)
    assert changed[0].path == path
    payload = RepositoryContext(tmp_path).build(ModelContext(changed[0], sql), patch, [])
    assert "+select * from raw.orders" in payload["diff"]
    provider = Mock()
    provider.review.return_value = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr("dbt_reviewer.cli.OpenAIReviewer", lambda **_: provider)
    patchfile = tmp_path / "change.diff"
    patchfile.write_text(patch)
    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--diff",
                str(patchfile),
                "--require-semantic",
                "--format",
                "json",
            ]
        )
        == 0
    )
    provider.review.assert_called_once()
    assert {f["check_id"] for f in json.loads(capsys.readouterr().out)} == {
        "D001",
        "SELECT_STAR",
    }


@pytest.mark.parametrize("setting", ["rules", "exclude_rules"])
def test_unknown_rule_selector_is_configuration_failure(setting):
    from dbt_reviewer.lint import SQLFluffCheck
    from dbt_reviewer.models import ChangedFile

    context = ModelContext(ChangedFile("models/a.sql", frozenset({1})), "select * from orders")
    with pytest.raises(ValueError, match="Unknown SQLFluff rule or group"):
        SQLFluffCheck(**{setting: "NOT_A_RULE"}).run(context)


def test_custom_model_paths_cover_review_and_parent_discovery(tmp_path, capsys):
    (tmp_path / "dbt_project.yml").write_text("name: custom\nmodel-paths: [transformations]\n")
    patchfile, patch = prepare(
        tmp_path, "", "select * from raw.orders\n", "transformations/orders.sql"
    )
    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--diff",
                str(patchfile),
                "--no-llm",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert {f["check_id"] for f in json.loads(capsys.readouterr().out)} == {
        "D001",
        "SELECT_STAR",
    }
    current = "select id from {{ ref('orders') }}\n"
    _, patch = prepare(tmp_path, "", current, "transformations/current.sql")
    change = parse_diff(patch, model_paths(tmp_path))[0]
    payload = RepositoryContext(tmp_path).build(ModelContext(change, current), patch, [])
    assert payload["direct_upstream"][0]["metadata"]["path"] == "transformations/orders.sql"


def test_new_wildcard_consequence_on_unchanged_line_is_reported(tmp_path):
    before = "with src as (select 1 as id)\nselect *\nfrom src\n"
    after = before.replace("from src", "from unknown_source")
    _, patch = prepare(tmp_path, before, after)
    findings = review(tmp_path, parse_diff(patch), diff_text=patch)
    assert any(f.check_id == "SELECT_STAR" and f.line == 2 for f in findings)


def test_parse_failure_on_unchanged_line_is_visible(tmp_path):
    before = "select (\nid\nfrom orders\n"
    after = before.replace("\nid\n", "\norder_id\n")
    _, patch = prepare(tmp_path, before, after)
    findings = review(tmp_path, parse_diff(patch), diff_text=patch)
    assert any(f.check_id == "SQLFLUFF:PRS" for f in findings)


@pytest.mark.parametrize("context", [0, 3])
@pytest.mark.parametrize(
    "before,after",
    [
        ("select id\nfrom orders\n", "select id, amount\nfrom orders\n"),
        ("-- start\nselect id\nfrom orders\n-- end\n", "select id\nfrom orders\n"),
        ("select id\nfrom orders\n", "-- start\nselect id\nfrom orders\n-- end\n"),
        ("", "select 1\n"),
    ],
)
def test_before_sql_reconstruction_handles_hunks_and_deletions(tmp_path, before, after, context):
    _, patch = prepare(tmp_path, before, after, context=context)
    assert previous_sql(after, patch, "models/orders.sql") == before


@pytest.mark.parametrize("path", ["../external", "/external", "{{ var('path') }}"])
def test_unsupported_model_roots_fail_explicitly(tmp_path, path):
    import yaml

    (tmp_path / "dbt_project.yml").write_text(yaml.safe_dump({"model-paths": [path]}))
    with pytest.raises(ValueError, match="model-paths"):
        model_paths(tmp_path)
