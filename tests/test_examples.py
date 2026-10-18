"""Public examples use the bundled fixture and the actual CLI, with no network."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from examples.prepare import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("DBT_REVIEW_MODEL", None)
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, env=env, text=True, capture_output=True
    )


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_prepared_repo_cli_end_to_end(tmp_path, scenario):
    repo = tmp_path / scenario
    prepared = run("examples/prepare.py", scenario, str(repo))
    assert prepared.returncode == 0, prepared.stderr
    result = run(
        "-m",
        "dbt_reviewer",
        "--repo",
        str(repo),
        "--no-llm",
        "--format",
        "json",
        "--diff",
        f"examples/diffs/{scenario}.diff",
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    expected = {"D001", "SELECT_STAR"} if scenario == "hardcoded_relation" else set()
    assert {f["check_id"] for f in json.loads(result.stdout)} == expected
    demo = run("examples/demo.py", scenario, "--no-llm")
    assert demo.returncode == 0 and not demo.stderr
    if not expected:
        assert demo.stdout == "No findings.\n"
    else:
        assert demo.stdout == (ROOT / "examples/outputs/hardcoded_relation.txt").read_text()


def test_prepare_refuses_to_overwrite(tmp_path):
    (tmp_path / "keep.txt").write_text("user content")
    result = run("examples/prepare.py", "join_fanout", str(tmp_path))
    assert result.returncode == 2
    assert (tmp_path / "keep.txt").read_text() == "user content"
    assert not (tmp_path / "models").exists()


def test_semantic_demo_without_key_fails_visibly():
    result = run("examples/demo.py", "wrong_join_key", "--format", "json")
    assert result.returncode == 2
    assert "OPENAI_API_KEY is not set" in result.stderr
    assert json.loads(result.stdout) == []


def test_saved_semantic_json_has_valid_fixture_references(tmp_path):
    from examples.prepare import prepare
    from tests.eval.corpus import assert_references

    repo = prepare("wrong_join_key", tmp_path / "repo")
    findings = json.loads((ROOT / "examples/outputs/wrong_join_key.json").read_text())
    assert {f["check_id"] for f in findings} == {"JOIN_KEY"}
    assert all(f["source"] == "semantic" and f["evidence"] for f in findings)
    assert_references(repo, findings)
