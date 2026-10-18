"""Minimal Jinja source adaptation on SQLGlot's lexer; no SQL rule logic."""

import re
from dataclasses import dataclass

from jinja2 import Environment, TemplateSyntaxError
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import TokenError


class RepositoryTokenizer(Postgres.Tokenizer):
    IDENTIFIERS = ['"', "`", ("[", "]")]


@dataclass(frozen=True)
class TemplateToken:
    text: str
    kind: str
    offset: int


def template_tokens(sql: str) -> list[TemplateToken]:
    """Find templates outside SQL strings/comments without executing them."""
    try:
        raw = RepositoryTokenizer().tokenize(sql)
    except TokenError as exc:
        raise ValueError("Cannot tokenize SQL; check quoting or unsupported syntax.") from exc
    templates = []
    consumed = 0
    literal_ranges = []
    for item in raw:
        start, end = item.start, item.end + 1
        if "STRING" in item.token_type.name or item.token_type.name == "IDENTIFIER":
            literal_ranges.append((start, end))
        if start < consumed or not sql.startswith(("{{", "{%"), start):
            continue
        expression = sql.startswith("{{", start)
        # Reuse Jinja's lexer for quoted delimiters and nested dictionaries.
        # Lexing does not render templates or execute repository code.
        consumed = start
        try:
            for _, kind, value in Environment().lex(sql[start:]):
                consumed += len(value)
                if kind == ("variable_end" if expression else "block_end"):
                    break
            else:
                raise ValueError("Unclosed Jinja expression or statement.")
        except TemplateSyntaxError as exc:
            raise ValueError("Invalid Jinja expression or statement.") from exc
        text = sql[start:consumed]
        emits_sql = expression and not re.match(r"{{-?\s*config\s*\(", text)
        templates.append(TemplateToken(text, "template" if emits_sql else "statement", start))
    for match in re.finditer(r"{#.*?#}", sql, re.DOTALL):
        if not any(start <= match.start() < end for start, end in literal_ranges):
            templates.append(TemplateToken(match.group(), "statement", match.start()))
    return templates


def masked_sql(sql: str) -> tuple[str, list[tuple[int, int]]]:
    """Same-length placeholders keep parser/linter positions in original source."""
    chars = list(sql)
    spans = []
    for token in template_tokens(sql):
        start, end = token.offset, token.offset + len(token.text)
        spans.append((start, end))
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = "_" if token.kind == "template" else " "
    return "".join(chars), spans


def sql_changed(before: str | None, after: str) -> bool:
    """Skip ordinary comment/whitespace edits; keep raw Jinja and literal changes."""
    if before is None:
        return True

    def signature(sql):
        templates = template_tokens(sql)
        tokens = RepositoryTokenizer().tokenize(masked_sql(sql)[0])
        # Hints and executable comments can affect SQL semantics. Review them.
        if any(c.lstrip().startswith(("+", "!")) for t in tokens for c in t.comments):
            raise ValueError("SQL directive requires review")
        return (
            [(t.token_type, t.text) for t in tokens],
            [t.text for t in templates if not t.text.startswith("{#")],
        )

    try:
        return signature(before) != signature(after)
    except (ValueError, TokenError):
        return True
