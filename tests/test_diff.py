import pytest

from dbt_reviewer.diff import DiffError, parse_diff


def patch(path="models/orders.sql"):
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n"
        "@@ -1,2 +1,3 @@\n"
        " select\n-    old_column\n+    order_id,\n+    amount\n"
    )


def test_multiple_hunks_and_files():
    text = patch() + "@@ -10 +11 @@\n-old\n+new\n" + patch("models/customers.sql")
    changed = parse_diff(text)
    assert changed[0].added_lines == {2, 3, 11}
    assert changed[1].path == "models/customers.sql"


def test_renamed_model_uses_destination_path():
    text = (
        "diff --git a/models/old.sql b/models/new.sql\n"
        "similarity index 90%\nrename from models/old.sql\nrename to models/new.sql\n"
        "--- a/models/old.sql\n+++ b/models/new.sql\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert parse_diff(text)[0].path == "models/new.sql"


@pytest.mark.parametrize("path", ["models/schema.yml", "macros/macro.sql", "tests/test.sql"])
def test_non_model_files_are_skipped(path):
    assert parse_diff(patch(path)) == []


def test_deleted_model_is_skipped():
    text = (
        "diff --git a/models/old.sql b/models/old.sql\ndeleted file mode 100644\n"
        "--- a/models/old.sql\n+++ /dev/null\n@@ -1 +0,0 @@\n-select 1\n"
    )
    assert parse_diff(text) == []


@pytest.mark.parametrize(
    "text", ["not a diff", "--- a/models/a.sql\n+++ b/models/a.sql\n@@ -1 +1 @@\n"]
)
def test_malformed_input(text):
    with pytest.raises(DiffError):
        parse_diff(text)


def test_path_traversal_is_rejected():
    with pytest.raises(DiffError, match="Unsafe"):
        parse_diff(patch("../models/orders.sql"))
