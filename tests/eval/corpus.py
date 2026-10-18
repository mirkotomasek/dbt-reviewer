"""One catalog shares four public diffs with the ten-case evaluation corpus."""

from dataclasses import dataclass
from pathlib import Path

from examples.prepare import EXAMPLES, ROOT, prepare_patch


@dataclass(frozen=True)
class Case:
    name: str
    semantic_id: str | None = None
    anchor: str | None = None
    deterministic_ids: tuple[str, ...] = ()

    @property
    def patch(self) -> str:
        public = EXAMPLES / "diffs" / f"{self.name}.diff"
        path = public if public.exists() else ROOT / "tests/eval/diffs" / f"{self.name}.diff"
        return path.read_text(encoding="utf-8")

    def prepare(self, destination: Path) -> Path:
        return prepare_patch(self.patch, destination)


CASES = (
    Case("comment_only"),
    Case("hardcoded_relation", deterministic_ids=("D001", "SELECT_STAR")),
    Case("strings_and_comments"),
    Case("join_fanout", "JOIN_FANOUT", "on orders.order_id = payments.order_id"),
    Case("wrong_join_key", "JOIN_KEY", "on orders.customer_id = payments.order_id"),
    Case("payment_grain"),
    Case("prompt_injection", "JOIN_KEY", "on orders.customer_id = payments.order_id"),
    Case("safe_aggregation"),
    Case("double_fanout", "JOIN_FANOUT", "left join"),
    Case(
        "json_ci", "JOIN_KEY", "on orders.customer_id = payments.order_id", ("D001", "SELECT_STAR")
    ),
)


def assert_references(repo, findings):
    for finding in findings:
        path = repo / finding["file"]
        assert path.is_file()
        assert 1 <= finding["line"] <= len(path.read_text().splitlines())
        for evidence in finding["evidence"]:
            ref = evidence["reference"]
            source = (repo / ref["file"]).resolve()
            assert source.is_relative_to(repo.resolve()) and source.is_file()
            assert 1 <= ref["line"] <= ref["end_line"] <= len(source.read_text().splitlines())
