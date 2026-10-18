"""Parse unified Git patches into current-file line locations."""

import codecs
from pathlib import Path, PurePosixPath
from typing import cast

import yaml
from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

from dbt_reviewer.models import ChangedFile


class DiffError(ValueError):
    """The input is not a supported unified patch."""


def destination_path(entry) -> str:
    """Decode Git's C-quoted UTF-8 paths before classification or safety checks."""
    path: str = entry.target_file
    if path.startswith('"'):
        if not path.endswith('"'):
            raise DiffError("Unclosed quoted Git path.")
        try:
            decoded = cast(bytes, codecs.escape_decode(path[1:-1].encode("utf-8"))[0])
            path = decoded.decode("utf-8", errors="surrogateescape")
        except ValueError as exc:
            raise DiffError("Invalid quoted Git path.") from exc
    return path[2:] if path.startswith(("a/", "b/")) else path


def model_paths(repo: Path) -> tuple[str, ...]:
    """Read dbt's model roots without rendering project configuration."""
    project = repo / "dbt_project.yml"
    if not project.exists():
        return ("models",)
    try:
        config = yaml.safe_load(project.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError("Cannot read model-paths from dbt_project.yml.") from exc
    if not isinstance(config, dict):
        raise ValueError("dbt_project.yml must contain a mapping.")
    paths = config.get("model-paths", ["models"])
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError("model-paths must be a list of relative directory names.")
    for path in paths:
        parts = PurePosixPath(path)
        if parts.is_absolute() or ".." in parts.parts or "{{" in path:
            raise ValueError("model-paths must contain literal repository-relative directories.")
    return tuple(paths)


def parse_diff(text: str, roots: tuple[str, ...] = ("models",)) -> list[ChangedFile]:
    if not text.strip():
        return []
    try:
        patch = PatchSet(text)
    except (UnidiffParseError, ValueError, IndexError) as exc:
        raise DiffError(f"Malformed unified diff: {exc}") from exc
    if not patch:
        raise DiffError("Input contains no unified file diff.")

    changed: dict[str, dict] = {}
    for entry in patch:
        # unidiff also calls a zero-context deletion at line 1 a removed
        # file; only /dev/null actually denotes file deletion in Git patches.
        if entry.target_file == "/dev/null" or entry.is_binary_file:
            continue
        # Use the destination path, including for renames.
        path = destination_path(entry)
        parts = PurePosixPath(path)
        if parts.is_absolute() or ".." in parts.parts:
            raise DiffError(f"Unsafe diff path: {path}")
        if parts.suffix != ".sql" or not any(
            parts.is_relative_to(PurePosixPath(root)) for root in roots
        ):
            continue
        record = changed.setdefault(path, {"added": set(), "deleted": set(), "expected": {}})
        for hunk in entry:
            cursor = hunk.target_start + (1 if hunk.target_length == 0 else 0)
            for line in hunk:
                if line.is_removed:
                    record["deleted"].add(cursor)
                elif line.is_added or line.is_context:
                    number = line.target_line_no
                    if number is None:
                        continue
                    value = line.value.rstrip("\r\n")
                    if number in record["expected"] and record["expected"][number] != value:
                        raise DiffError(f"Conflicting destination lines for {path}:{number}")
                    record["expected"][number] = value
                    if line.is_added:
                        record["added"].add(number)
                    cursor = number + 1
    return [
        ChangedFile(
            path,
            frozenset(r["added"]),
            frozenset(r["deleted"] - r["added"]),
            tuple(sorted(r["expected"].items())),
        )
        for path, r in changed.items()
    ]


def previous_sql(sql: str, diff_text: str, path: str) -> str | None:
    """Reverse supplied hunks in memory; no Git checkout or patch application."""
    entries = [entry for entry in PatchSet(diff_text) if destination_path(entry) == path]
    if not entries:
        return None
    lines = sql.splitlines(keepends=True)
    for entry in reversed(entries):
        for hunk in reversed(entry):
            start = hunk.target_start - bool(hunk.target_length)
            original = [line.value for line in hunk if line.is_context or line.is_removed]
            lines[start : start + hunk.target_length] = original
    return "".join(lines)
