"""Text patterns shared by SQL searches and live-image membership checks.

Preserve TagGUI's existing database rules; this is not a new search syntax.
LIKE folds ASCII case only, with %/_ wildcards and no ESCAPE clause. Other
glob-based filters (name, path and marking labels) retain their own rules.
"""
from fnmatch import translate
from functools import lru_cache
import re


_ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def contains_pattern(value):
    return f'%{value}%'


def tag_pattern(value):
    """None denotes the exact, case-sensitive tag equality path."""
    return value.replace('*', '%').replace('?', '_') if '*' in value or '?' in value else None


def palette_pattern(value):
    needle = str(value).strip().upper()
    return tag_pattern(needle) if '*' in needle or '?' in needle else contains_pattern(needle)


def _compile_like(pattern):
    # Escape glob syntax that SQLite LIKE treats literally. fnmatch's
    # translation uses atomic groups for interior stars, avoiding a chain of
    # backtracking .* groups when a query contains repeated % wildcards.
    glob = ''.join({'%': '*', '_': '?', '*': '[*]', '?': '[?]', '[': '[[]'}.get(c, c)
                   for c in pattern.split('\0', 1)[0].translate(_ASCII_LOWER))
    return re.compile(translate(glob)).match


_cached_like = lru_cache(maxsize=256)(_compile_like)


def matches_like(text, pattern):
    """Match the default SQLite LIKE rules without IO or a DB connection."""
    if text is None:
        return False
    matcher = _cached_like(pattern) if len(pattern) <= 4096 else _compile_like(pattern)
    return matcher(str(text).split('\0', 1)[0].translate(_ASCII_LOWER)) is not None
