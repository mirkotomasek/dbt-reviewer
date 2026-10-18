"""Review orchestration, independent of CLI and output format."""

from collections.abc import Sequence
from pathlib import Path

from dbt_reviewer.checks import DEFAULT_CHECKS, Check, ModelContext
from dbt_reviewer.context import RepositoryContext
from dbt_reviewer.diff import previous_sql
from dbt_reviewer.models import ChangedFile, Finding
from dbt_reviewer.semantic import (
    SEMANTIC_CHECK_IDS,
    SemanticReviewer,
    normalize_severity,
    validate_grounding,
)
from dbt_reviewer.sql import sql_changed


def review(
    repo: Path,
    changed_files: Sequence[ChangedFile],
    checks: Sequence[Check] = DEFAULT_CHECKS,
    *,
    semantic: SemanticReviewer | None = None,
    diff_text: str = "",
    diagnostics: list[str] | None = None,
) -> list[Finding]:
    root = repo.resolve()
    findings = []
    contexts = []
    for changed in changed_files:
        if not changed.added_lines and not changed.deletion_points:
            continue
        path = (root / changed.path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Model path escapes repository: {changed.path}")
        try:
            sql = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Cannot read current model {changed.path}: {exc}") from exc
        lines = sql.splitlines()
        if max(changed.added_lines, default=0) > len(lines):
            raise ValueError(
                f"Diff line numbers exceed current model {changed.path}; apply the diff before reviewing."
            )
        for number, expected in changed.expected_lines:
            if number > len(lines) or lines[number - 1] != expected:
                raise ValueError(
                    f"Diff does not match current model {changed.path}:{number}; apply the diff before reviewing."
                )
        if any(point > len(lines) + 1 for point in changed.deletion_points):
            raise ValueError(
                f"Deletion location exceeds current model {changed.path}; apply the diff before reviewing."
            )
        context = ModelContext(changed, sql, previous_sql(sql, diff_text, changed.path))
        contexts.append(context)
        for check in checks:
            findings.extend(check.run(context))
    # Finish deterministic review first. Context/provider failures are contained
    # per model and never discard deterministic results or other model reviews.
    if semantic is not None and contexts:
        repository = None
        for context in contexts:
            if not sql_changed(context.previous_sql, context.sql):
                continue
            try:
                if repository is None:
                    repository = RepositoryContext(root)
                deterministic = [
                    f
                    for f in findings
                    if f.file == context.changed_file.path and f.source == "deterministic"
                ]
                payload = repository.build(context, diff_text, deterministic)
                semantic_findings = semantic.review(payload)
                # Validate findings from any injected provider, too.
                for finding in semantic_findings:
                    if (
                        finding.check_id not in SEMANTIC_CHECK_IDS
                        or finding.source != "semantic"
                        or finding.file != context.changed_file.path
                        or finding.line not in context.semantic_lines
                        or finding.confidence is None
                    ):
                        raise ValueError("Invalid semantic finding")
                    validate_grounding(finding, payload)
                findings.extend(normalize_severity(finding) for finding in semantic_findings)
            except Exception as exc:
                if diagnostics is not None:
                    # Provider errors can contain request data or credentials.
                    # Expose only their type, never the raw exception body.
                    diagnostics.append(
                        f"Semantic review skipped for {context.changed_file.path} "
                        f"({type(exc).__name__}); deterministic findings retained."
                    )
    # Normalize order and remove exact duplicates from overlapping hunks/rules.
    findings = deduplicate(findings)
    unique = {finding.model_dump_json(): finding for finding in findings}
    return sorted(unique.values(), key=lambda f: (f.file, f.line or 0, f.check_id, f.message))


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """Suppress recognizable semantic restatements of deterministic root causes.

    Keep join/grain issues even when the same line also selects a wildcard.
    Ambiguous overlap is retained rather than hiding a distinct concern.
    """
    result = []
    for finding in findings:
        if finding.source == "semantic":
            message = finding.message.lower()
            duplicate = any(
                other.source == "deterministic"
                and other.file == finding.file
                and (
                    (other.check_id == finding.check_id and other.line == finding.line)
                    or (
                        finding.check_id == "DBT_MODEL"
                        and other.line == finding.line
                        and (
                            (
                                other.check_id == "SELECT_STAR"
                                and any(
                                    phrase in message
                                    for phrase in ("select *", "wildcard", "all upstream columns")
                                )
                            )
                            or (other.check_id == "D001" and "hardcoded" in message)
                        )
                    )
                )
                for other in findings
            )
            if duplicate:
                continue
        result.append(finding)
    return result
