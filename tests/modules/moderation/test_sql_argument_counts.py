"""Every parameterised query must be passed as many arguments as it declares.

asyncpg raises `InterfaceError` when the two disagree, and nothing catches that
before runtime: the type checker cannot see inside a SQL string, and the linter
has no opinion about it. It is also exactly the mistake a schema change invites,
because adding a column means editing the column list, the placeholder list and
the argument list in three separate places.

This walks the AST instead of executing anything, so it needs no database.
"""

import ast
import re
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[3] / 'app'

# asyncpg's parameterised query methods. Their first positional argument is the
# SQL; everything after it is a bind parameter.
QUERY_METHODS = frozenset({'execute', 'fetch', 'fetchrow', 'fetchval'})

PLACEHOLDER = re.compile(r'\$(\d+)')


def _call_sites() -> list[tuple[str, int, int, int]]:
    """Every literal-SQL query call in the app, as (path, line, declared, passed)."""
    sites: list[tuple[str, int, int, int]] = []
    for path in sorted(APP_ROOT.rglob('*.py')):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in QUERY_METHODS or not node.args:
                continue

            sql = node.args[0]
            # Queries assembled at runtime (f-strings, helper-built strings) carry
            # their parameters in a list, so the count is not visible here.
            if not isinstance(sql, ast.Constant) or not isinstance(sql.value, str):
                continue
            # `conn.fetch(query, *params)` likewise hides the count behind a splat.
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                continue

            placeholders = {int(n) for n in PLACEHOLDER.findall(sql.value)}
            if not placeholders:
                continue

            relative = path.relative_to(APP_ROOT.parent)
            sites.append((str(relative), node.lineno, max(placeholders), len(node.args) - 1))
    return sites


CALL_SITES = _call_sites()


def test_the_scan_actually_finds_queries():
    # A refactor that renames the methods or moves the package would otherwise
    # turn this file into a test that passes by inspecting nothing.
    assert len(CALL_SITES) > 50


@pytest.mark.parametrize(
    ('path', 'line', 'declared', 'passed'),
    CALL_SITES,
    ids=[f'{path}:{line}' for path, line, _, _ in CALL_SITES],
)
def test_placeholder_count_matches_argument_count(path, line, declared, passed):
    assert declared == passed, (
        f'{path}:{line} declares ${declared} but is passed {passed} arguments'
    )
