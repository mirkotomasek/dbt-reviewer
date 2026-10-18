"""Public CLI input, output modes, advisory behavior, and enforcement."""

import io
import json
from unittest.mock import Mock

import pytest

from dbt_reviewer.cli import main
from dbt_reviewer.semantic import normalize_response
from tests.helpers import issue, make_diff, model, patch, setup_repo


def test_cli_malformed_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("invalid"))
    assert main(["--repo", str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "no unified file diff" in output.err


def test_cli_missing_repository(tmp_path, capsys):
    assert main(["--repo", str(tmp_path / "missing")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_missing_diff_file(tmp_path, capsys):
    assert main(["--repo", str(tmp_path), "--diff", str(tmp_path / "missing.diff")]) == 2
    assert "dbt-review:" in capsys.readouterr().err


def test_strict_missing_key_preserves_output_and_takes_precedence_over_threshold(
    tmp_path, monkeypatch, capsys
):
    sql = "select id from raw.orders\n"
    model(tmp_path, sql)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(patch("", sql)))
    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--require-semantic",
                "--fail-on",
                "error",
                "--format",
                "json",
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert json.loads(result.out)[0]["check_id"] == "D001"
    assert "Required semantic review did not complete" in result.err


@pytest.mark.parametrize("fails,expected", [(False, 0), (True, 2)])
def test_strict_provider_completion(tmp_path, monkeypatch, capsys, fails, expected):
    sql = "select 1\n"
    model(tmp_path, sql)
    monkeypatch.setattr("sys.stdin", io.StringIO(patch("", sql)))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class Reviewer:
        def __init__(self, **kwargs):
            pass

        def review(self, payload):
            if fails:
                raise TimeoutError("private provider content")
            return []

    monkeypatch.setattr("dbt_reviewer.cli.OpenAIReviewer", Reviewer)
    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--require-semantic",
                "--format",
                "json",
            ]
        )
        == expected
    )
    output = capsys.readouterr()
    assert json.loads(output.out) == []
    assert "private provider content" not in output.err


def test_strict_empty_diff_needs_no_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    provider = Mock(side_effect=AssertionError("no request is needed"))
    monkeypatch.setattr("dbt_reviewer.cli.OpenAIReviewer", provider)
    assert main(["--repo", str(tmp_path), "--require-semantic"]) == 0
    provider.assert_not_called()
    assert capsys.readouterr().out == "No findings.\n"


def test_strict_disabled_is_invalid(tmp_path, capsys):
    assert main(["--repo", str(tmp_path), "--require-semantic", "--no-llm"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--verbose", "--explain"])
def test_verbose_alias_reaches_renderer(tmp_path, monkeypatch, capsys, flag):
    setup_repo(tmp_path)

    class Provider:
        def review(self, payload):
            return normalize_response({"issues": [issue()]}, payload)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("dbt_reviewer.cli.OpenAIReviewer", lambda **kwargs: Provider())
    monkeypatch.setattr("sys.stdin", io.StringIO(make_diff()))
    assert main(["--repo", str(tmp_path), flag]) == 0
    assert "[confirmed_fact]" in capsys.readouterr().out


@pytest.mark.parametrize(
    "output_format,threshold,sql,exit_code,footer",
    [
        ("text", None, "select * from raw.orders", 0, None),
        ("text", "none", "select id from raw.orders", 0, None),
        ("text", "error", "select * from raw.orders", 1, "FAIL (--fail-on error)"),
        ("text", "warning", "select * from {{ ref('orders') }}", 1, "FAIL (--fail-on warning)"),
        ("text", "error", "select * from {{ ref('orders') }}", 0, "PASS (--fail-on error)"),
        ("text", "warning", "select 1", 0, None),
        ("json", "warning", "select * from {{ ref('orders') }}", 1, None),
    ],
)
def test_findings_exit_status_and_footer_follow_enforcement_policy(
    tmp_path, monkeypatch, capsys, output_format, threshold, sql, exit_code, footer
):
    sql += "\n"
    model(tmp_path, sql)
    monkeypatch.setattr("sys.stdin", io.StringIO(patch("", sql)))
    arguments = ["--repo", str(tmp_path), "--no-llm", "--format", output_format]
    if threshold is not None:
        arguments += ["--fail-on", threshold]
    assert main(arguments) == exit_code
    output = capsys.readouterr()
    assert not output.err
    if output_format == "json":
        assert json.loads(output.out)[0]["check_id"] == "SELECT_STAR"
    elif sql == "select 1\n":
        assert output.out == "No findings.\n"
    else:
        assert "finding" in output.out
    if footer:
        assert f"CI result: {footer}" in output.out
    else:
        assert "CI result:" not in output.out
