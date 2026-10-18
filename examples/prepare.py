"""Copy the minimal fixture and apply a saved patch to a new, isolated checkout."""

import argparse
import shutil
from pathlib import Path

from unidiff import PatchSet

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/jaffle_shop"
EXAMPLES = ROOT / "examples"
SCENARIOS = ("hardcoded_relation", "join_fanout", "safe_aggregation", "wrong_join_key")


def prepare_patch(patch_text: str, destination: Path) -> Path:
    # Refuse an existing destination so running an example cannot overwrite work.
    shutil.copytree(FIXTURE, destination)
    root = destination.resolve()
    for entry in PatchSet(patch_text):
        name = entry.target_file.removeprefix("b/")
        model = (root / name).resolve()
        if not model.is_relative_to(root):
            raise ValueError("Example patch escapes destination")
        lines = model.read_text(encoding="utf-8").splitlines(True) if model.exists() else []
        for hunk in reversed(entry):
            start = hunk.source_start - bool(hunk.source_length)
            before = [line.value for line in hunk if line.is_context or line.is_removed]
            after = [line.value for line in hunk if line.is_context or line.is_added]
            if lines[start : start + hunk.source_length] != before:
                raise ValueError(f"Example patch does not match baseline: {name}")
            lines[start : start + hunk.source_length] = after
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("".join(lines), encoding="utf-8")
    return destination


def prepare(scenario: str, destination: Path) -> Path:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    return prepare_patch((EXAMPLES / "diffs" / f"{scenario}.diff").read_text(), destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("destination", type=Path, help="new directory; must not exist")
    args = parser.parse_args()
    try:
        prepare(args.scenario, args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"prepare: {exc}\n")
    print(f"Prepared {args.scenario} in {args.destination}")


if __name__ == "__main__":
    main()
