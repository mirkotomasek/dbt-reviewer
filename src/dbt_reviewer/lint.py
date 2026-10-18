"""SQLFluff is the deterministic SQL rule engine; this adapter scopes its findings."""

from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cached_property

from dbt_reviewer.models import Finding, ModelContext
from dbt_reviewer.sql import masked_sql

# Quality/correctness rules, without imposing formatting or naming conventions.
DEFAULT_RULES = "AM01,AM02,AM04,AM07,AM08,AM09,CV05,ST01,ST02,ST03,ST04,ST08,ST10,ST12"


@dataclass
class SQLFluffCheck:
    dialect: str = "duckdb"
    rules: str = DEFAULT_RULES
    exclude_rules: str = ""
    id: str = "SQLFLUFF"

    @cached_property
    def linter(self):
        from sqlfluff.core import FluffConfig, Linter
        from sqlfluff.core.errors import SQLFluffUserError
        from sqlfluff.core.rules import get_ruleset

        try:
            config = FluffConfig(
                configs={
                    "core": {
                        "dialect": self.dialect,
                        "templater": "raw",
                        "rules": self.rules,
                        "exclude_rules": self.exclude_rules,
                    }
                }
            )
            # SQLFluff logs unknown selectors but otherwise succeeds with no rules.
            # A typo in a CI configuration must fail explicitly.
            references = (
                get_ruleset()
                .get_rulepack(FluffConfig(overrides={"dialect": self.dialect}))
                .reference_map
            )
            for selectors in (self.rules, self.exclude_rules):
                for selector in filter(None, (s.strip() for s in selectors.split(","))):
                    if selector != "all" and not any(
                        fnmatchcase(reference, selector) for reference in references
                    ):
                        raise ValueError(f"Unknown SQLFluff rule or group: {selector}")
            return Linter(config=config)
        except (SQLFluffUserError, KeyError) as exc:
            raise ValueError(
                "Invalid SQLFluff configuration; check --dialect and --rules."
            ) from exc

    def run(self, context: ModelContext) -> list[Finding]:
        sql, _ = masked_sql(context.sql)
        violations: list[dict] = [
            v.to_dict() for v in self.linter.lint_string(sql).get_violations()
        ]
        previous: Counter[tuple[str, str]] = Counter()
        if context.previous_sql is not None:
            try:
                before, _ = masked_sql(context.previous_sql)
                previous.update(
                    (v.rule_code(), v.desc())
                    for v in self.linter.lint_string(before).get_violations()
                )
            except ValueError:
                # An invalid previous template must not hide current diagnostics.
                pass
        selected = []
        for violation in violations:
            key = (violation["code"], violation["description"])
            existed = previous[key] > 0
            previous[key] -= 1
            if (
                violation["code"] in {"PRS", "LXR", "TMP"}
                or violation["start_line_no"] in context.semantic_lines
                or (context.previous_sql is not None and not existed)
            ):
                selected.append(violation)
        return [
            Finding(
                check_id="SELECT_STAR" if v["code"] == "AM04" else f"SQLFLUFF:{v['code']}",
                engine_rule=f"SQLFLUFF:{v['code']}",
                file=context.changed_file.path,
                line=v["start_line_no"],
                severity="warning",
                source="deterministic",
                suggestion="Select the required columns explicitly."
                if v["code"] == "AM04"
                else None,
                message=(
                    "Wildcard projection makes the output schema implicit and can propagate unexpected upstream columns."
                    if v["code"] == "AM04"
                    else (
                        "Unable to lint masked SQL: " if v["code"] in {"PRS", "LXR", "TMP"} else ""
                    )
                    + v["description"]
                ),
            )
            for v in selected
        ]
