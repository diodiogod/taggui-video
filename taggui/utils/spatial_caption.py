"""Detection and explicit, user-triggered spatial caption corrections."""

from __future__ import annotations

import re

from utils.settings import DEFAULT_SETTINGS, settings


BODY_PARTS = (
    "arm", "hand", "leg", "foot", "eye", "ear", "cheek", "eyebrow",
    "temple", "shoulder", "elbow", "wrist", "finger", "hip", "knee",
    "calf", "thigh", "ankle", "buttock", "side",
)
_PART = "|".join(sorted(BODY_PARTS, key=len, reverse=True))
_BARE_PART = "|".join(
    sorted((part for part in BODY_PARTS if part != "side"), key=len, reverse=True)
)
_OWNER = r"(?:his|her|their|its|the\s+(?:man|woman|person|subject)(?:'s)?)"
BODY_DIRECTION_RE = re.compile(
    rf"\b(?P<owner>{_OWNER})\s+(?P<side>left|right)\s+"
    rf"(?P<part>{_PART})(?P<plural>s)?\b",
    re.IGNORECASE,
)
BODY_DIRECTION_BARE_RE = re.compile(
    rf"\b(?P<side>left|right)\s+(?P<part>{_BARE_PART})(?P<plural>s)?\b",
    re.IGNORECASE,
)
FRAME_SIDE_RE = re.compile(
    r"\b(?:on\s+)?(?:the\s+)?(?:left|right)(?:-hand)?\s+side(?:\s+of\s+(?:the\s+)?(?:image|frame|shot))?\b"
    r"|\b(?:image|frame|shot)[- ](?:left|right)\b",
    re.IGNORECASE,
)
DEPTH_RE = re.compile(
    r"\b(?:in\s+the\s+)?(?:foreground|background)\b",
    re.IGNORECASE,
)
SUBJECT_SIDE_RE = re.compile(
    r"\b(?:on|at|toward|to)\s+(?:the\s+)?(?:left|right)(?:-hand)?(?:\s+side)?\b",
    re.IGNORECASE,
)


def spatial_expression_kind(text: str) -> str | None:
    """Classify text for review without claiming that it is incorrect."""
    if BODY_DIRECTION_RE.search(text) or BODY_DIRECTION_BARE_RE.search(text):
        return "body"
    if SUBJECT_SIDE_RE.search(text) or FRAME_SIDE_RE.search(text) or DEPTH_RE.search(text):
        return "position"
    return None


def has_spatial_expression(text: str) -> bool:
    return bool(spatial_expression_spans(text))


def spatial_reference_label() -> str:
    reference = settings.value(
        'spatial_reference_noun',
        DEFAULT_SETTINGS['spatial_reference_noun'],
        type=str,
    ).strip().lower()
    return 'IMAGE' if reference == 'image' else 'FRAME'


def spatial_expression_spans(text: str) -> list[tuple[int, int, str]]:
    """Return non-overlapping spatial phrase spans for editor highlighting."""
    highlight_depth = settings.value(
        'spatial_highlight_depth_expressions',
        DEFAULT_SETTINGS['spatial_highlight_depth_expressions'],
        type=bool,
    )
    candidates = []
    patterns = [
        ("body", BODY_DIRECTION_RE),
        ("body", BODY_DIRECTION_BARE_RE),
        ("position", FRAME_SIDE_RE),
        ("position", SUBJECT_SIDE_RE),
    ]
    if highlight_depth:
        patterns.append(("position", DEPTH_RE))
    for kind, pattern in patterns:
        candidates.extend((m.start(), m.end(), kind) for m in pattern.finditer(text))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    spans = []
    for candidate in candidates:
        if spans and candidate[0] < spans[-1][1]:
            continue
        spans.append(candidate)
    return spans


def spatial_gesture_actions(text: str) -> set[str]:
    kind = spatial_expression_kind(text)
    if kind == "body":
        return {
            "word_left", "word_right", "frame_left", "frame_right",
            "background", "foreground", "background_left",
            "background_right", "foreground_left", "foreground_right",
        }
    if kind == "position":
        return {
            "frame_left", "frame_right", "background", "foreground",
            "background_left", "background_right",
            "foreground_left", "foreground_right",
        }
    return set()


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _set_body_word(text: str, side: str) -> str:
    def replace(match: re.Match) -> str:
        original = match.group("side")
        return match.group(0).replace(original, _match_case(original, side), 1)

    text = BODY_DIRECTION_RE.sub(replace, text)
    return BODY_DIRECTION_BARE_RE.sub(replace, text)


def _to_frame_side(text: str, side: str) -> str:
    if spatial_reference_label() == 'IMAGE':
        frame_side = f"the {side} side of the image"
    else:
        frame_side = f"the {side} side of the frame"
    had_side_expression = bool(
        BODY_DIRECTION_RE.search(text)
        or BODY_DIRECTION_BARE_RE.search(text)
        or FRAME_SIDE_RE.search(text)
        or SUBJECT_SIDE_RE.search(text)
    )

    def owned_body(match: re.Match) -> str:
        plural = match.group("plural") or ""
        return f"{match.group('owner')} {match.group('part')}{plural} on {frame_side}"

    def bare_body(match: re.Match) -> str:
        plural = match.group("plural") or ""
        return f"{match.group('part')}{plural} on {frame_side}"

    updated = BODY_DIRECTION_RE.sub(owned_body, text)
    updated = BODY_DIRECTION_BARE_RE.sub(bare_body, updated)
    if FRAME_SIDE_RE.search(updated):
        updated = FRAME_SIDE_RE.sub(f"on {frame_side}", updated)
    else:
        updated = SUBJECT_SIDE_RE.sub(f"on {frame_side}", updated)
    if not had_side_expression and spatial_expression_kind(text) == "position":
        updated = f"{updated.rstrip()} on {frame_side}"
    return updated


def _set_depth(text: str, depth: str) -> str:
    replacement = f"in the {depth}"
    if DEPTH_RE.search(text):
        return DEPTH_RE.sub(replacement, text)
    # Depth is always an explicit manual choice; it is never inferred.
    if spatial_expression_kind(text) is not None:
        return f"{text.rstrip()} {replacement}"
    return text


def apply_spatial_action(text: str, action: str) -> str:
    """Apply one explicit action selected by the user."""
    if action == "word_left":
        return _set_body_word(text, "left")
    if action == "word_right":
        return _set_body_word(text, "right")
    if action == "frame_left":
        return _to_frame_side(text, "left")
    if action == "frame_right":
        return _to_frame_side(text, "right")
    if action == "background":
        return _set_depth(text, "background")
    if action == "foreground":
        return _set_depth(text, "foreground")
    if action.startswith("background_"):
        return _set_depth(_to_frame_side(text, action.rsplit("_", 1)[1]), "background")
    if action.startswith("foreground_"):
        return _set_depth(_to_frame_side(text, action.rsplit("_", 1)[1]), "foreground")
    return text
