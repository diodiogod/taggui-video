"""Reusable, case-aware text replacement and swapping."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextTransformOptions:
    first: str
    second: str
    swap: bool = True
    whole_words: bool = True
    match_case: bool = False
    preserve_case: bool = True
    use_regex: bool = False


def _apply_case(source: str, replacement: str) -> str:
    if not source or not replacement:
        return replacement
    if source.isupper():
        return replacement.upper()
    if source.islower():
        return replacement.lower()
    if source[0].isupper() and source[1:].islower():
        return replacement[:1].upper() + replacement[1:].lower()
    return replacement


def _pattern(value: str, *, whole_words: bool, use_regex: bool) -> str:
    pattern = value if use_regex else re.escape(value)
    if whole_words:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    return pattern


def transform_text(text: str, options: TextTransformOptions) -> tuple[str, int, int]:
    """Return transformed text and A→B / B→A replacement counts."""
    if not options.first:
        return text, 0, 0
    flags = 0 if options.match_case else re.IGNORECASE
    first_pattern = _pattern(
        options.first,
        whole_words=options.whole_words,
        use_regex=options.use_regex,
    )
    second_pattern = _pattern(
        options.second,
        whole_words=options.whole_words,
        use_regex=options.use_regex,
    )
    if options.swap and not options.second:
        return text, 0, 0

    count_first = 0
    count_second = 0

    def replacement_for(match: re.Match, replacement: str) -> str:
        if options.use_regex and not options.swap:
            # Preserve normal re.sub back-reference behavior in replace mode.
            value = match.expand(replacement)
        else:
            value = replacement
        return _apply_case(match.group(0), value) if options.preserve_case else value

    if not options.swap:
        def replace_one(match: re.Match) -> str:
            nonlocal count_first
            count_first += 1
            return replacement_for(match, options.second)

        return re.sub(first_pattern, replace_one, text, flags=flags), count_first, 0

    combined = re.compile(
        rf"(?P<first>{first_pattern})|(?P<second>{second_pattern})",
        flags,
    )

    def swap_one(match: re.Match) -> str:
        nonlocal count_first, count_second
        if match.group("first") is not None:
            count_first += 1
            return replacement_for(match, options.second)
        count_second += 1
        return replacement_for(match, options.first)

    return combined.sub(swap_one, text), count_first, count_second
