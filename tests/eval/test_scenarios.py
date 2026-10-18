"""Offline mechanics for all cases; opt-in real-provider property assertions."""

import json
import os

import pytest

from dbt_reviewer.cli import main
from dbt_reviewer.context import RepositoryContext
from dbt_reviewer.diff import parse_diff
from dbt_reviewer.models import ModelContext
from dbt_reviewer.semantic import normalize_response
from tests.eval.corpus import CASES, assert_references


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_offline_corpus(tmp_path, capsys, case):
    repo = case.prepare(tmp_path / "repo")
    patch = tmp_path / "change.diff"
    patch.write_text(case.patch)
    # Also verify the context each online evaluation will receive.
    for changed in parse_diff(case.patch):
        sql = (repo / changed.path).read_text()
        payload = RepositoryContext(repo).build(ModelContext(changed, sql), case.patch, [])
        assert payload["evidence_sources"]
        if case.semantic_id:
            assert len(payload["direct_upstream"]) == 2 or "hardcoded" in changed.path
    assert main(["--repo", str(repo), "--diff", str(patch), "--no-llm", "--format", "json"]) == 0
    output = capsys.readouterr()
    assert not output.err
    findings = json.loads(output.out)
    assert sorted(f["check_id"] for f in findings) == sorted(case.deterministic_ids)
    assert_references(repo, findings)
    if case.name == "hardcoded_relation":
        wildcard = next(f for f in findings if f["check_id"] == "SELECT_STAR")
        assert wildcard["engine_rule"] == "SQLFLUFF:AM04"
        assert "wildcard" in wildcard["message"].lower()
        hardcoded = next(f for f in findings if f["check_id"] == "D001")
        assert "ref()" in hardcoded["suggestion"] and "source()" in hardcoded["suggestion"]


@pytest.mark.semantic
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not set")
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_live_corpus(tmp_path, capsys, case):
    repo = case.prepare(tmp_path / "repo")
    patch = tmp_path / "change.diff"
    patch.write_text(case.patch)
    code = main(
        ["--repo", str(repo), "--diff", str(patch), "--format", "json", "--require-semantic"]
    )
    output = capsys.readouterr()
    assert code == 0, output.err
    assert not output.err, output.err
    findings = json.loads(output.out)
    assert_references(repo, findings)
    deterministic = [f for f in findings if f["source"] == "deterministic"]
    assert sorted(f["check_id"] for f in deterministic) == sorted(case.deterministic_ids)
    semantic = [f for f in findings if f["source"] == "semantic"]
    if case.semantic_id is None:
        assert semantic == []
        return
    matches = [f for f in semantic if f["check_id"] == case.semantic_id]
    assert matches, findings
    for finding in semantic:
        assert finding["confidence"] in {"medium", "high"}
        assert finding["severity"] in {"warning", "error"}
        assert finding["suggestion"] and finding["evidence"]
        assert finding["line"] in next(
            c.added_lines for c in parse_diff(case.patch) if c.path == finding["file"]
        )
    for finding in matches:
        lines = (repo / finding["file"]).read_text().splitlines()
        # Accept a join predicate, the neighboring join, or affected aggregate.
        relevant = [
            i
            for i, line in enumerate(lines, 1)
            if case.anchor in line
            or any(
                token in line
                for token in ("join payments", "join order_status_events", "count(", "sum(")
            )
        ]
        assert any(abs(finding["line"] - line) <= 1 for line in relevant)
        if case.semantic_id == "JOIN_FANOUT":
            assert finding["severity"] == "warning"
        if case.name == "double_fanout":
            # The literal event rows establish multiplicity in this model itself.
            assert any(
                e["reference"]["file"] == finding["file"]
                and e["reference"]["line"] <= 19
                and e["reference"]["end_line"] >= 16
                for e in finding["evidence"]
            ), finding
        else:
            assert any(
                e["reference"]["file"].startswith("models/staging/") for e in finding["evidence"]
            ), finding


def test_json_ci_contract_with_injected_provider(tmp_path, monkeypatch, capsys):
    """Offline JSON/source plumbing is independent of semantic accuracy above."""
    case = CASES[-1]
    repo = case.prepare(tmp_path / "repo")
    patch = tmp_path / "change.diff"
    patch.write_text(case.patch)

    class Provider:
        def review(self, payload):
            if payload["file"].endswith("eval_hardcoded.sql"):
                return []
            line = next(i for i, s in enumerate(payload["sql"].splitlines(), 1) if case.anchor in s)
            return normalize_response(
                {
                    "issues": [
                        {
                            "check_id": "JOIN_KEY",
                            "line": line,
                            "severity": "error",
                            "confidence": "high",
                            "message": "The join compares customer and order identifiers.",
                            "suggestion": "Join orders.order_id = payments.order_id.",
                            "evidence": [
                                {
                                    "status": "confirmed_fact",
                                    "statement": "Customer ID comes from user_id.",
                                    "reference": {
                                        "file": "models/staging/stg_orders.sql",
                                        "line": 4,
                                        "end_line": 4,
                                    },
                                }
                            ],
                        }
                    ]
                },
                payload,
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr("dbt_reviewer.cli.OpenAIReviewer", lambda **_: Provider())
    assert (
        main(
            ["--repo", str(repo), "--diff", str(patch), "--format", "json", "--fail-on", "warning"]
        )
        == 1
    )
    output = capsys.readouterr()
    assert not output.err
    findings = json.loads(output.out)
    assert {f["source"] for f in findings} == {"deterministic", "semantic"}
    assert {f["check_id"] for f in findings} == {"D001", "SELECT_STAR", "JOIN_KEY"}
    fields = {
        "check_id",
        "file",
        "line",
        "severity",
        "message",
        "suggestion",
        "confidence",
        "engine_rule",
        "source",
        "evidence",
    }
    assert all(set(f) == fields for f in findings)
    assert_references(repo, findings)
