"""Render concise human output or the complete machine-readable finding schema."""

import json
from collections import Counter
from collections.abc import Sequence

from dbt_reviewer.models import Finding


def render_findings(
    findings: Sequence[Finding], output_format: str, *, verbose: bool = False
) -> str:
    if output_format == "json":
        return json.dumps([finding.model_dump() for finding in findings], indent=2)
    if not findings:
        return "No findings."
    counts: Counter[str] = Counter(f.severity for f in findings)
    totals = ", ".join(
        f"{counts[level]} {level}{'s' if counts[level] != 1 else ''}"
        for level in ("error", "warning", "info")
        if counts[level]
    )
    blocks = [f"{len(findings)} finding{'s' if len(findings) != 1 else ''} ({totals})"]
    for finding in findings:
        location = finding.file
        if finding.line is not None:
            location += f":{finding.line}"
        confidence = f" [{finding.confidence} confidence]" if finding.confidence else ""
        block = f"{finding.severity.upper()} {finding.check_id} {location}{confidence}\n{finding.message}"
        if verbose:
            for entry in finding.evidence:
                ref = entry.reference
                block += (
                    f"\n[{entry.status}] {entry.statement} ({ref.file}:{ref.line}-{ref.end_line})"
                )
            if finding.engine_rule:
                block += f"\nEngine rule: {finding.engine_rule}"
        elif finding.evidence:
            facts = [e for e in finding.evidence if e.status == "confirmed_fact"]
            entry = next(
                (e for e in facts if e.reference.file.endswith(".sql")),
                next(iter(facts), finding.evidence[0]),
            )
            block += f"\nEvidence: {' '.join(entry.statement.split())}"
        if finding.suggestion:
            block += f"\nFix: {finding.suggestion}"
        blocks.append(block)
    if not verbose and any(f.evidence for f in findings):
        blocks.append("Run with --verbose to show repository evidence.")
    return "\n\n".join(blocks)
