"""CLI review policies, concise human output, and structured stdout."""

import argparse
import os
import sys
from pathlib import Path

from dbt_reviewer.diff import model_paths, parse_diff
from dbt_reviewer.output import render_findings
from dbt_reviewer.review import review
from dbt_reviewer.semantic import OpenAIReviewer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review changed dbt SQL models (DuckDB dialect).")
    parser.add_argument("--repo", required=True, type=Path, help="dbt repository directory")
    parser.add_argument("--diff", type=Path, help="unified diff file (default: stdin)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--verbose",
        "--explain",
        action="store_true",
        help="show full reasoning and repository evidence in human output",
    )
    parser.add_argument("--no-llm", action="store_true", help="disable semantic review")
    parser.add_argument("--model", help="OpenAI model (default: DBT_REVIEW_MODEL or gpt-6-luna)")
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "none"),
        default="none",
        help="exit 1 at this severity threshold (default: none)",
    )
    parser.add_argument(
        "--require-semantic",
        action="store_true",
        help="exit 2 if any changed model's semantic review is incomplete",
    )
    args = parser.parse_args(argv)

    try:
        if args.require_semantic and args.no_llm:
            raise ValueError("--require-semantic cannot be combined with --no-llm.")
        if not args.repo.is_dir():
            raise ValueError(f"Repository directory does not exist: {args.repo}")
        if args.diff is None and sys.stdin.isatty():
            raise ValueError("Supply a diff using stdin or --diff FILE.")
        patch = args.diff.read_text(encoding="utf-8") if args.diff else sys.stdin.read()
        changed = parse_diff(patch, model_paths(args.repo))
        diagnostics: list[str] = []
        semantic = None
        reviewable = any(file.added_lines or file.deletion_points for file in changed)
        if not args.no_llm and reviewable:
            if os.environ.get("OPENAI_API_KEY"):
                semantic = OpenAIReviewer(model=args.model)
            else:
                diagnostics.append(
                    "Semantic review skipped: OPENAI_API_KEY is not set; ran deterministic checks only."
                )
        findings = review(
            args.repo,
            changed,
            semantic=semantic,
            diff_text=patch,
            diagnostics=diagnostics,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"dbt-review: {exc}", file=sys.stderr)
        return 2

    strict_failure = args.require_semantic and bool(diagnostics)
    if strict_failure:
        diagnostics.append("Required semantic review did not complete; exiting with code 2.")
    for diagnostic in diagnostics:
        print(diagnostic, file=sys.stderr)
    threshold_reached = args.fail_on != "none" and any(
        f.severity == "error" or (args.fail_on == "warning" and f.severity == "warning")
        for f in findings
    )
    print(render_findings(findings, args.format, verbose=args.verbose))
    if args.format == "text" and findings and args.fail_on != "none":
        if strict_failure:
            print("\nCI result: FAIL (required semantic review incomplete)")
        else:
            result = "FAIL" if threshold_reached else "PASS"
            print(f"\nCI result: {result} (--fail-on {args.fail_on})")
    if strict_failure:
        return 2
    return 1 if threshold_reached else 0
