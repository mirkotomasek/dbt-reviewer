"""Run a saved example through the real CLI in a temporary fixture checkout."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from prepare import EXAMPLES, SCENARIOS, prepare

from dbt_reviewer.cli import main as review_main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--no-llm", action="store_true", help="deterministic checks only")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--model")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="dbt-review-demo-") as directory:
        repo = prepare(args.scenario, Path(directory) / "jaffle_shop")
        argv = [
            "--repo",
            str(repo),
            "--diff",
            str(EXAMPLES / "diffs" / f"{args.scenario}.diff"),
            "--format",
            args.format,
        ]
        if args.model:
            argv.extend(("--model", args.model))
        if args.verbose:
            argv.append("--verbose")
        # A semantic showcase must fail visibly if semantic review is unavailable.
        argv.append(
            "--no-llm"
            if args.no_llm or args.scenario == "hardcoded_relation"
            else "--require-semantic"
        )
        return review_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
