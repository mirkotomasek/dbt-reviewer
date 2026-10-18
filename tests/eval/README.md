# Selected evaluation corpus

Exactly ten scenarios, with one shared minimal Jaffle Shop fixture. Four public
input diffs live in `examples/diffs/`; the remaining six live here in `diffs/`.
`corpus.py` defines expectations, and the preparer applies each diff to an isolated
copy. No warehouse/dbt execution is needed.

| Case | Expected findings | Offline verification | Optional live verification |
| --- | --- | --- | --- |
| 1. `comment_only` | None | Existing wildcard ignored; zero provider calls | No-op filter returns clean |
| 2. `hardcoded_relation` | D001 + SELECT_STAR | IDs, friendly wildcard wording, engine rule, ref/source fix | No redundant semantic findings |
| 3. `strings_and_comments` | None | SQL literals/comments do not trigger local rules | No semantic findings |
| 4. `join_fanout` | JOIN_FANOUT | Inputs/context valid; no unrelated local findings | Category, warning, confidence, relevant anchor, upstream evidence |
| 5. `wrong_join_key` | JOIN_KEY | Inputs/context valid | Category, severity/confidence, relevant anchor, upstream evidence |
| 6. `payment_grain` | None | No local findings | Intentional payment grain stays clean |
| 7. `prompt_injection` | JOIN_KEY | Inputs/context valid | Wrong join still reported despite malicious comments |
| 8. `safe_aggregation` | None | No local findings | Payment aggregation before join stays clean |
| 9. `double_fanout` | JOIN_FANOUT | Inputs/context valid | Multiplying two detail branches is flagged |
| 10. `json_ci` | D001 + SELECT_STAR + JOIN_KEY | Injected provider tests real normalization/CLI serialization, fields, sources, citations and exit 1 | Actual provider mixed findings with JSON-only stdout |

```sh
uv run pytest                         # offline by default, even with a key set
uv run pytest -m semantic -v           # explicit opt-in; 10 initial provider calls; comment-only case makes none
uv run pytest -m semantic -k safe_aggregation -v  # one selected live control
```

Without `OPENAI_API_KEY`, live cases skip. With a key, API failures, grounding
rejections and expectation mismatches fail. Calls incur API usage. Each eligible model gets one request with at most three
total attempts on transient/invalid-response failure; no run-wide budget is used.
No exact LLM prose is asserted. Tests check categories, changed/relevant locations,
severity/confidence, suggestions, source distinctions, and existing citation ranges.
They do not automatically grade the full reasoning or prove the factual meaning
of a citation. Read representative [live outputs](../../examples/outputs/) for that.

Important interpretation: payment-row SQL plus payment key declarations support
a *possible* multi-payment order; missing `order_id` uniqueness alone does not
prove duplicates. The fanout example's fix is to aggregate payments to order grain
or count distinct orders as appropriate. With two detail branches, aggregate each
branch separately before joining; aggregating after multiplication cannot repair
the measures. Intentional payment-grain output is valid.

Existing unit tests retain coverage beyond this compact corpus for parser, API,
grounding and CI edge cases. Offline injected responses test mechanics, not model
accuracy. These ten authored cases are not a held-out performance benchmark.
