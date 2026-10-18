"""Reuse SQLFluff rules; retain only a small dbt relation policy on SQLGlot's AST."""

from dataclasses import dataclass
from typing import Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from dbt_reviewer.lint import DEFAULT_RULES, SQLFluffCheck
from dbt_reviewer.models import Finding, ModelContext
from dbt_reviewer.sql import masked_sql


class Check(Protocol):
    id: str

    def run(self, context: ModelContext) -> list[Finding]: ...


@dataclass
class HardcodedRelation:
    """dbt dependency policy absent from SQLFluff's built-in SQL rules."""

    dialect: str = "duckdb"
    id: str = "D001"

    def run(self, context: ModelContext) -> list[Finding]:
        sql, templates = masked_sql(context.sql)
        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except (ParseError, TokenError):
            # SQLFluff owns parse diagnostics; do not invent tables from invalid SQL.
            return []
        findings = []
        for statement in statements:
            if statement is None:
                continue
            for table in statement.find_all(exp.Table):
                parts = table.parts
                if not isinstance(table.this, exp.Identifier) or len(parts) < 2:
                    continue
                first = min(p.meta.get("start", 0) for p in parts)
                last = max(p.meta.get("end", first) for p in parts) + 1
                if any(first < end and start < last for start, end in templates):
                    continue
                first_line = context.sql.count("\n", 0, first) + 1
                last_line = first_line + context.sql[first:last].count("\n")
                overlap = context.changed_file.added_lines & set(range(first_line, last_line + 1))
                if not overlap:
                    continue
                findings.append(
                    Finding(
                        check_id=self.id,
                        file=context.changed_file.path,
                        line=min(overlap),
                        severity="error",
                        source="deterministic",
                        message=f"Hardcoded relation `{context.sql[first:last]}` bypasses dbt dependency tracking.",
                        suggestion="Use `ref()` for a dbt model or `source()` for a declared source.",
                    )
                )
        return findings


def default_checks(
    dialect: str = "duckdb", rules: str = DEFAULT_RULES, exclude_rules: str = ""
) -> tuple[Check, ...]:
    return (HardcodedRelation(dialect), SQLFluffCheck(dialect, rules, exclude_rules))


DEFAULT_CHECKS = default_checks()
