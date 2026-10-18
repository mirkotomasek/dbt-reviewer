# AI-Powered dbt Code Reviewer

A Python CLI that reviews a git diff of dbt models using deterministic SQL checks
and optional LLM reasoning over repository context. This prototype produces
findings with file, line, severity, explanation, and suggested fix.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```sh
uv sync --frozen --extra dev
uv run python examples/demo.py hardcoded_relation
```

The [bundled Jaffle Shop fixture](tests/fixtures/jaffle_shop/README.md) needs no
database, dbt installation, external clone, or API key. For semantic review,
export `OPENAI_API_KEY`; see [.env.example](.env.example). `.env` is not loaded automatically.

Review a checkout whose current files already match the diff:

```sh
git diff HEAD~1 | uv run dbt-review --repo .
uv run dbt-review --repo ./dbt-project --diff change.diff --format json
```

Use `--no-llm` for local checks only.

## Checks and examples

| Type | Checks |
| --- | --- |
| Deterministic | `D001`: qualified hardcoded relations bypassing `ref()`/`source()`; `SELECT_STAR`: unresolved wildcard output; selected SQLFluff quality rules |
| Semantic | `JOIN_KEY`, `JOIN_FANOUT`, `GRAIN_CHANGE`, `NAMING`, `DBT_MODEL`: repository-supported key, grain, naming, and structural concerns |

[Sample diffs and real outputs](examples/README.md) can be read without setup:

| Example | Saved output |
| --- | --- |
| Hardcoded wildcard | [D001 error + SELECT_STAR warning](examples/outputs/hardcoded_relation.txt) |
| Join fanout | [Conditional JOIN_FANOUT warning](examples/outputs/join_fanout.txt) |
| Payments aggregated before joining | [No findings](examples/outputs/safe_aggregation.txt) |
| Wrong join key | [Text](examples/outputs/wrong_join_key.txt) / [JSON with evidence](examples/outputs/wrong_join_key.json) |

```sh
# Requires OPENAI_API_KEY; semantic demos require successful review
uv run python examples/demo.py join_fanout
uv run python examples/demo.py safe_aggregation
```

The helper prepares a temporary checkout and runs the real CLI. Saved semantic
outputs are real provider responses; their wording can vary.

## Architecture and AI design

```text
diff → changed models → deterministic checks → relevant context → LLM
     → validate and normalize findings → deduplicate → text / JSON
```

[`review.py`](src/dbt_reviewer/review.py) coordinates independent checks, context
retrieval, and output. SQLGlot handles the hardcoded-relation rule; SQLFluff supplies
existing SQL rules. New deterministic checks implement `Check.run(ModelContext)`.

The [semantic adapter](src/dbt_reviewer/semantic.py) uses OpenAI Responses with
`gpt-6-luna` and Pydantic structured output: one focused provider adapter keeps the
workflow small without an agent framework. Override with `--model` or
`DBT_REVIEW_MODEL`. Each eligible model gets one request, with at most three total
attempts on transient failures or invalid responses. Permanent API errors fail immediately.

Only the current model, diff, direct `ref()` parents, and relevant schema declarations
are sent to OpenAI (`store=False`). Comment/whitespace-only changes skip the LLM;
Jinja and repository macros are never executed. The domain-independent prompt treats
repository content as untrusted evidence and distinguishes safe detail-grain joins
from harmful fanout. Python validates response shape, anchors, and citation ranges.

## Output and CI

`--verbose` shows full evidence; JSON retains source, confidence, engine rule, and
citations alongside the finding fields. Stdout contains only the selected report;
diagnostics go to stderr. Clean reports are `No findings.` or `[]`.

```sh
git diff HEAD~1 | uv run dbt-review --repo . --format json --fail-on warning
# Block only errors, and fail if semantic review cannot complete:
uv run dbt-review --repo ./dbt-project --diff change.diff \
  --format json --fail-on error --require-semantic
```

Default mode is advisory. Exit **0** means the policy passes; **1** means findings
meet `--fail-on` (`warning` includes errors); **2** means invalid input or incomplete
required semantic review. Missing keys/provider failures preserve local findings;
`--require-semantic` makes incomplete review fail CI. Set a job timeout for total duration.

## Verification

```sh
uv run pytest                 # offline; never calls the LLM
uv run pytest -m semantic -v   # optional live evaluation; requires key, incurs usage
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

The [ten scenarios](tests/eval/README.md) cover diff awareness, false positives,
safe/unsafe joins, prompt injection, and JSON/CI. Offline tests mock the provider;
live tests assert properties and skip without credentials. Semantic evaluation
focuses on `JOIN_KEY` and `JOIN_FANOUT`; the other categories lack live accuracy
coverage. Existing CI runs offline checks. This small corpus does not establish general accuracy.

## Limitations and next steps

- **Static analysis only:** no dbt or warehouse execution. Key tests are declarations,
  not observed cardinalities; fanout findings describe conditional risks and are
  capped at warning. Valid citations do not guarantee correct LLM reasoning.
- **Partial dbt context:** direct parents only; no manifest graph, transitive lineage,
  or singular-test discovery. Package/versioned refs, sources, and complex Jinja
  have limited support. Renames leaving stale `schema.yml` entries are not checked.
- **Limited SQL policy:** DuckDB dialect; unqualified physical relations and predicates
  such as `ON 1=1` are outside current deterministic coverage. Before/after lint
  matching is heuristic; parse diagnostics may appear on unchanged lines.

With more time, prioritize independent evaluation data, better dbt identity/context
resolution, and response caching with measured latency and cost before broader
checks or CI integrations.
