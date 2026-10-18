# Runnable examples

Run commands from the repository root after `uv sync --frozen --extra dev`.
All inputs use the [minimal bundled Jaffle Shop fixture](../tests/fixtures/jaffle_shop/README.md).
The helper copies it to a temporary directory, applies the selected diff, invokes
the real CLI, and cleans up. No external clone or database is needed.

| Example | Input | Saved stdout | Expected behavior |
| --- | --- | --- | --- |
| Hardcoded wildcard | [diff](diffs/hardcoded_relation.diff) | [text](outputs/hardcoded_relation.txt) | D001 + SELECT_STAR |
| Join fanout | [diff](diffs/join_fanout.diff) | [text](outputs/join_fanout.txt) | Conditional JOIN_FANOUT risk |
| Safe aggregation | [diff](diffs/safe_aggregation.diff) | [text](outputs/safe_aggregation.txt) | No findings |
| Wrong join key | [diff](diffs/wrong_join_key.diff) | [text](outputs/wrong_join_key.txt), [JSON](outputs/wrong_join_key.json) | JOIN_KEY grounded in staging SQL |

```sh
uv run python examples/demo.py hardcoded_relation
# Export OPENAI_API_KEY before the following real semantic calls:
uv run python examples/demo.py join_fanout
uv run python examples/demo.py safe_aggregation
uv run python examples/demo.py wrong_join_key --format json
```

The deterministic example needs no API key. Semantic demos use
`--require-semantic`, so a skipped/failed provider request cannot masquerade as a
clean result. `--no-llm` explicitly runs only local checks on any example;
it does not demonstrate semantic detection. `--verbose` includes full evidence.

To use the CLI directly, first prepare a **new** destination (choose an unused path):

```sh
uv run python examples/prepare.py join_fanout /tmp/jaffle-fanout-review
uv run dbt-review --repo /tmp/jaffle-fanout-review \
  --diff examples/diffs/join_fanout.diff --require-semantic
```

The CLI reviews the current checkout; it does not apply patches. Pointing a new-file
diff directly at the baseline fixture would fail because those files do not exist yet.
The preparer refuses to overwrite existing directories.

The saved semantic stdout comes from actual OpenAI runs using the default
`gpt-6-luna` model on 18 October 2026. Text outputs use the CLI formatter on captured JSON responses; the wrong-key
text and JSON therefore describe the same real response. They are representative output, not authored mocks or prose snapshots
for automated tests. Reproduce with the commands above, redirecting stdout to
the corresponding file under `examples/outputs/`; diagnostics stay on stderr.
