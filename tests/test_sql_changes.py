"""The cheap candidate gate skips only lexical no-ops, preserving SQL and Jinja."""

import pytest

from dbt_reviewer.sql import sql_changed


@pytest.mark.parametrize(
    "before,after",
    [
        ("select id from orders", "-- comment\nselect  id\nfrom orders /* comment */"),
        ("select id from orders -- comment", "select id from orders"),
        ("select 1", "{# Jinja comment #}\nselect 1"),
    ],
)
def test_comments_and_whitespace_are_not_semantic_candidates(before, after):
    assert not sql_changed(before, after)


@pytest.mark.parametrize(
    "before,after",
    [
        ("select 'a b'", "select 'ab'"),
        ("select 1", "select 2"),
        ('select "a b" from orders', 'select "ab" from orders'),
        ("select id from {{ ref('orders') }}", "select id from {{ ref('events') }}"),
        (
            "{{ config(materialized='view') }} select 1",
            "{{ config(materialized='table') }} select 1",
        ),
        ("{% set x = 1 %} select {{ x }}", "{% set x = 2 %} select {{ x }}"),
        ("select id from orders where id > 0", "select id from orders"),
        ("select id from orders", "select /*+ hint */ id from orders"),
        ("select '", "select '"),
        (None, "select 1"),
    ],
)
def test_sql_jinja_directives_and_uncertain_parses_remain_candidates(before, after):
    assert sql_changed(before, after)
