"""Read current SQL, direct ref parents and relevant schema declarations."""

import json
import re
from pathlib import Path

import yaml
from unidiff import PatchSet

from dbt_reviewer.diff import destination_path, model_paths
from dbt_reviewer.models import Finding, ModelContext
from dbt_reviewer.sql import template_tokens

MAX_FILE_BYTES = 64_000
MAX_PARENTS = 8
MAX_PAYLOAD_CHARS = 120_000
REF = re.compile(r"\bref\(\s*(['\"])([^'\"]+)\1\s*(?:,\s*(['\"])([^'\"]+)\3\s*)?\)")


class ContextError(ValueError):
    pass


class RepositoryContext:
    def __init__(self, repo: Path):
        self.root = repo.resolve()
        self.model_roots = model_paths(self.root)

    def read(self, relative: str, limit: int = MAX_FILE_BYTES) -> str:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ContextError(f"Context path escapes repository: {relative}")
        with path.open("rb") as stream:
            contents = stream.read(limit + 1)
        if len(contents) > limit:
            raise ContextError(f"Context file exceeds {limit} bytes: {relative}")
        return contents.decode("utf-8")

    def inventory(self) -> list[Path]:
        return sorted(
            {
                path
                for root in self.model_roots
                for path in (self.root / root).rglob("*")
                if path.suffix in {".sql", ".yml", ".yaml"}
                and path.is_file()
                and path.resolve().is_relative_to(self.root)
            }
        )

    @staticmethod
    def ref_names(sql: str) -> list[str]:
        return list(
            dict.fromkeys(
                match[4] or match[2]
                for token in template_tokens(sql)
                if token.kind == "template"
                for match in REF.finditer(token.text)
            )
        )

    def yaml_metadata(self, files: list[Path], names: set[str], notes: list[str]) -> dict:
        declarations: dict = {name: [] for name in names}
        for path in files:
            if path.suffix not in {".yml", ".yaml"}:
                continue
            relative = path.relative_to(self.root).as_posix()
            try:
                raw = self.read(relative)
                document = yaml.compose(raw)
                if not isinstance(document, yaml.MappingNode):
                    continue
                for key, value in document.value:
                    if key.value != "models" or not isinstance(value, yaml.SequenceNode):
                        continue
                    for entry in value.value:
                        if not isinstance(entry, yaml.MappingNode):
                            continue
                        name = next((v.value for k, v in entry.value if k.value == "name"), None)
                        if name not in names:
                            continue
                        first = entry.start_mark.line + 1
                        last = entry.end_mark.line + bool(entry.end_mark.column)
                        text = "\n".join(raw.splitlines()[first - 1 : last])
                        declarations[name].append(
                            {
                                "path": relative,
                                "declaration": yaml.safe_load(yaml.serialize(entry)),
                                "source": {
                                    "file": relative,
                                    "line": first,
                                    "end_line": last,
                                    "text": text,
                                },
                            }
                        )
            except (yaml.YAMLError, OSError, UnicodeError, ContextError):
                notes.append(f"Could not read model YAML: {relative}; tests may be incomplete.")
        return declarations

    def build(self, context: ModelContext, diff_text: str, findings: list[Finding]) -> dict:
        files = self.inventory()
        notes = []
        parents = []
        for name in self.ref_names(context.sql):
            candidates = [p for p in files if p.suffix == ".sql" and p.stem == name]
            if len(candidates) != 1:
                notes.append(
                    f"Upstream model {name} is missing or ambiguous; its grain is unknown."
                )
            else:
                parents.append((name, candidates[0].relative_to(self.root).as_posix()))
        if len(parents) > MAX_PARENTS:
            notes.append(f"Direct parents capped at {MAX_PARENTS}; context is incomplete.")
        parents = parents[:MAX_PARENTS]
        current_name = Path(context.changed_file.path).stem
        declarations = self.yaml_metadata(files, {current_name, *(n for n, _ in parents)}, notes)
        upstream = [
            {
                "metadata": {"name": name, "path": path},
                "sql": self.read(path),
                "yaml": declarations[name],
            }
            for name, path in parents
        ]
        payload = {
            "file": context.changed_file.path,
            "changed_lines": sorted(context.semantic_lines),
            "diff": "".join(
                str(entry)
                for entry in PatchSet(diff_text)
                if destination_path(entry) == context.changed_file.path
            ),
            "sql": context.sql,
            "model_yaml": declarations[current_name],
            "direct_upstream": upstream,
            "deterministic_findings": [f.model_dump() for f in findings],
            "limitations": notes
            + [
                "Tests are declarations, not executed results.",
                "Only direct ref parents are included; macros, sources and package identity are not resolved.",
            ],
            "evidence_sources": [
                {
                    "file": context.changed_file.path,
                    "line": 1,
                    "end_line": len(context.sql.splitlines()),
                },
                *(
                    {
                        "file": p["metadata"]["path"],
                        "line": 1,
                        "end_line": len(p["sql"].splitlines()),
                    }
                    for p in upstream
                ),
                *(
                    {k: d["source"][k] for k in ("file", "line", "end_line")}
                    for items in declarations.values()
                    for d in items
                ),
            ],
        }
        if len(json.dumps(payload)) > MAX_PAYLOAD_CHARS:
            raise ContextError("Semantic context exceeds the payload budget.")
        return payload
