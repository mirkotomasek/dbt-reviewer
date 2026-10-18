"""Shared data contracts for review stages."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class ChangedFile:
    path: str
    added_lines: frozenset[int]
    # Destination insertion points of removed blocks (possibly just after EOF).
    deletion_points: frozenset[int] = frozenset()
    expected_lines: tuple[tuple[int, str], ...] = ()


@dataclass
class ModelContext:
    changed_file: ChangedFile
    sql: str
    previous_sql: str | None = None

    @property
    def semantic_lines(self) -> frozenset[int]:
        """Added lines and surviving lines immediately beside deletions."""
        length = len(self.sql.splitlines())
        adjacent = {
            line
            for point in self.changed_file.deletion_points
            for line in (point - 1, point)
            if 1 <= line <= length
        }
        return self.changed_file.added_lines | adjacent


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    file: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    status: Literal["confirmed_fact", "high_confidence_risk", "unknown"]
    statement: str = Field(min_length=1, max_length=2000)
    reference: EvidenceReference


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    file: str
    line: int | None = Field(default=None, ge=1)
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    engine_rule: str | None = None
    source: Literal["deterministic", "semantic"]
    evidence: list[Evidence] = Field(default_factory=list)
