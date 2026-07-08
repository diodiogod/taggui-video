import json

from dataclasses import dataclass
from enum import IntFlag

from PySide6.QtGui import QKeySequence

from utils.settings import settings


MAX_REVIEW_RANK = 5
REVIEW_BADGE_SCHEMA_SETTINGS_KEY = 'review_badge_schema'
REVIEW_BADGE_TEXT_COLOR_SETTINGS_KEY = 'review_badge_text_color'
REVIEW_BADGE_FONT_SIZE_SETTINGS_KEY = 'review_badge_font_size'
REVIEW_BADGE_CORNER_RADIUS_SETTINGS_KEY = 'review_badge_corner_radius'
DEFAULT_REVIEW_BADGE_TEXT_COLOR = '#FFFFFF'
DEFAULT_REVIEW_BADGE_FONT_SIZE = 9
DEFAULT_REVIEW_BADGE_CORNER_RADIUS = 5


class ReviewFlag(IntFlag):
    NONE = 0
    IDEA = 1 << 0
    WARNING = 1 << 1
    QUESTION = 1 << 2
    REJECT = 1 << 3


REVIEW_FLAG_ORDER: tuple[ReviewFlag, ...] = (
    ReviewFlag.REJECT,
    ReviewFlag.WARNING,
    ReviewFlag.QUESTION,
    ReviewFlag.IDEA,
)

REVIEW_FLAG_NAMES: dict[ReviewFlag, str] = {
    ReviewFlag.IDEA: 'idea',
    ReviewFlag.WARNING: 'warning',
    ReviewFlag.QUESTION: 'question',
    ReviewFlag.REJECT: 'reject',
}

REVIEW_FLAG_ALIASES: dict[str, ReviewFlag] = {
    'i': ReviewFlag.IDEA,
    '*': ReviewFlag.IDEA,
    'idea': ReviewFlag.IDEA,
    '!': ReviewFlag.WARNING,
    'warn': ReviewFlag.WARNING,
    'warning': ReviewFlag.WARNING,
    '?': ReviewFlag.QUESTION,
    'question': ReviewFlag.QUESTION,
    'ask': ReviewFlag.QUESTION,
    'x': ReviewFlag.REJECT,
    'reject': ReviewFlag.REJECT,
    'discard': ReviewFlag.REJECT,
}

ALL_REVIEW_FLAGS_MASK = int(
    ReviewFlag.IDEA
    | ReviewFlag.WARNING
    | ReviewFlag.QUESTION
    | ReviewFlag.REJECT
)


@dataclass(frozen=True)
class ReviewBadgeSpec:
    badge_id: str
    kind: str
    label: str
    title: str
    color: str
    shortcuts: tuple[str, ...]
    rank: int | None = None
    flag_name: str | None = None
    flag: ReviewFlag = ReviewFlag.NONE


_DEFAULT_BADGE_ROWS: tuple[dict, ...] = (
    {
        'badge_id': 'rank_1',
        'kind': 'rank',
        'rank': 1,
        'label': '1',
        'title': '',
        'color': '#FFC107',
        'shortcuts': ('1',),
    },
    {
        'badge_id': 'rank_2',
        'kind': 'rank',
        'rank': 2,
        'label': '2',
        'title': '',
        'color': '#3B82F6',
        'shortcuts': ('2',),
    },
    {
        'badge_id': 'rank_3',
        'kind': 'rank',
        'rank': 3,
        'label': '3',
        'title': '',
        'color': '#22C55E',
        'shortcuts': ('3',),
    },
    {
        'badge_id': 'rank_4',
        'kind': 'rank',
        'rank': 4,
        'label': '4',
        'title': '',
        'color': '#A855F7',
        'shortcuts': ('4',),
    },
    {
        'badge_id': 'rank_5',
        'kind': 'rank',
        'rank': 5,
        'label': '5',
        'title': '',
        'color': '#F97316',
        'shortcuts': ('5',),
    },
    {
        'badge_id': 'flag_reject',
        'kind': 'flag',
        'flag_name': 'reject',
        'flag': ReviewFlag.REJECT,
        'label': 'X',
        'title': '',
        'color': '#EF4444',
        'shortcuts': ('X',),
    },
    {
        'badge_id': 'flag_idea',
        'kind': 'flag',
        'flag_name': 'idea',
        'flag': ReviewFlag.IDEA,
        'label': '*',
        'title': '',
        'color': '#14B8A6',
        'shortcuts': ('8', 'Shift+8', 'I'),
    },
    {
        'badge_id': 'flag_warning',
        'kind': 'flag',
        'flag_name': 'warning',
        'flag': ReviewFlag.WARNING,
        'label': '!',
        'title': '',
        'color': '#F59E0B',
        'shortcuts': ('Shift+1', "'", 'W'),
    },
    {
        'badge_id': 'flag_question',
        'kind': 'flag',
        'flag_name': 'question',
        'flag': ReviewFlag.QUESTION,
        'label': '?',
        'title': '',
        'color': '#6366F1',
        'shortcuts': ('/', 'Shift+/'),
    },
)

REVIEW_FLAG_LABELS: dict[ReviewFlag, str] = {
    ReviewFlag.IDEA: next(row['label'] for row in _DEFAULT_BADGE_ROWS if row.get('flag') == ReviewFlag.IDEA),
    ReviewFlag.WARNING: next(row['label'] for row in _DEFAULT_BADGE_ROWS if row.get('flag') == ReviewFlag.WARNING),
    ReviewFlag.QUESTION: next(row['label'] for row in _DEFAULT_BADGE_ROWS if row.get('flag') == ReviewFlag.QUESTION),
    ReviewFlag.REJECT: next(row['label'] for row in _DEFAULT_BADGE_ROWS if row.get('flag') == ReviewFlag.REJECT),
}

_review_badge_specs_cache: tuple[ReviewBadgeSpec, ...] | None = None


def normalize_review_rank(raw_value) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        rank_value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return max(0, min(MAX_REVIEW_RANK, rank_value))


def normalize_review_flags(raw_value) -> int | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return None

    if isinstance(raw_value, IntFlag):
        return int(raw_value) & ALL_REVIEW_FLAGS_MASK

    if isinstance(raw_value, int):
        return int(raw_value) & ALL_REVIEW_FLAGS_MASK

    if isinstance(raw_value, str):
        token = str(raw_value or '').strip().lower()
        if not token:
            return 0
        return int(REVIEW_FLAG_ALIASES.get(token, ReviewFlag.NONE))

    if isinstance(raw_value, (list, tuple, set)):
        flags_value = 0
        for item in raw_value:
            normalized_item = normalize_review_flags(item)
            if normalized_item is None:
                continue
            flags_value |= int(normalized_item)
        return flags_value & ALL_REVIEW_FLAGS_MASK

    return None


def normalize_review_state(rank_value, flags_value) -> tuple[int, int]:
    normalized_rank = normalize_review_rank(rank_value)
    normalized_flags = normalize_review_flags(flags_value)

    normalized_rank = int(normalized_rank or 0)
    normalized_flags = int(normalized_flags or 0) & ALL_REVIEW_FLAGS_MASK

    if normalized_flags & int(ReviewFlag.REJECT):
        normalized_rank = 0

    return normalized_rank, normalized_flags


def serialize_review_flags(flags_value) -> list[str]:
    normalized_flags = int(normalize_review_flags(flags_value) or 0)
    return [
        REVIEW_FLAG_NAMES[flag]
        for flag in REVIEW_FLAG_ORDER
        if normalized_flags & int(flag)
    ]


def iter_review_flags(flags_value) -> list[ReviewFlag]:
    normalized_flags = int(normalize_review_flags(flags_value) or 0)
    return [
        flag
        for flag in REVIEW_FLAG_ORDER
        if normalized_flags & int(flag)
    ]


def parse_review_flag_token(token: str) -> ReviewFlag | None:
    normalized = str(token or '').strip().lower()
    if not normalized:
        return None
    return REVIEW_FLAG_ALIASES.get(normalized)


def has_review_marks(rank_value, flags_value) -> bool:
    normalized_rank, normalized_flags = normalize_review_state(rank_value, flags_value)
    return normalized_rank > 0 or normalized_flags != 0


def _normalize_badge_label(value, fallback: str) -> str:
    label = str(value or '').strip()
    return label[:4] if label else str(fallback)


def _normalize_badge_title(value) -> str:
    return str(value or '').strip()


def _normalize_badge_color(value, fallback: str) -> str:
    raw = str(value or '').strip()
    if not raw:
        return fallback
    if not raw.startswith('#'):
        raw = f'#{raw}'
    if len(raw) == 4:
        raw = '#' + ''.join(ch * 2 for ch in raw[1:])
    if len(raw) != 7:
        return fallback
    try:
        int(raw[1:], 16)
    except ValueError:
        return fallback
    return raw.upper()


def _normalize_shortcut_token(value) -> str:
    token = str(value or '').strip()
    if not token:
        return ''
    try:
        normalized = QKeySequence(token).toString(QKeySequence.SequenceFormat.PortableText)
    except Exception:
        normalized = ''
    return str(normalized or token).strip()


def _normalize_shortcut_tokens(raw_value, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw_value, str):
        candidates = raw_value.replace('\n', ',').split(',')
    elif isinstance(raw_value, (list, tuple, set)):
        candidates = list(raw_value)
    else:
        candidates = list(fallback)

    normalized_tokens = []
    seen = set()
    for candidate in candidates:
        token = _normalize_shortcut_token(candidate)
        if not token:
            continue
        lowered = token.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized_tokens.append(token)

    if normalized_tokens:
        return tuple(normalized_tokens)
    return tuple(_normalize_shortcut_token(item) for item in fallback if _normalize_shortcut_token(item))


def _build_badge_spec(default_row: dict, override_row: dict | None = None) -> ReviewBadgeSpec:
    override_row = override_row or {}
    badge_id = str(default_row['badge_id'])
    kind = str(default_row['kind'])
    fallback_shortcuts = tuple(default_row.get('shortcuts', ()))
    return ReviewBadgeSpec(
        badge_id=badge_id,
        kind=kind,
        label=_normalize_badge_label(override_row.get('label'), default_row.get('label', badge_id)),
        title=_normalize_badge_title(override_row.get('title')),
        color=_normalize_badge_color(override_row.get('color'), str(default_row.get('color', '#64748B'))),
        shortcuts=_normalize_shortcut_tokens(override_row.get('shortcuts'), fallback_shortcuts),
        rank=default_row.get('rank'),
        flag_name=default_row.get('flag_name'),
        flag=default_row.get('flag', ReviewFlag.NONE),
    )


def _load_badge_schema_overrides() -> dict[str, dict]:
    raw_value = settings.value(REVIEW_BADGE_SCHEMA_SETTINGS_KEY, defaultValue='', type=str)
    if not str(raw_value or '').strip():
        return {}
    try:
        parsed = json.loads(str(raw_value))
    except Exception:
        return {}
    if not isinstance(parsed, list):
        return {}
    overrides = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        badge_id = str(item.get('badge_id') or '').strip()
        if not badge_id:
            continue
        overrides[badge_id] = item
    return overrides


def _invalidate_review_badge_schema_cache(*_args):
    global _review_badge_specs_cache
    _review_badge_specs_cache = None


def _on_settings_changed(key: str, _value):
    if key == REVIEW_BADGE_SCHEMA_SETTINGS_KEY:
        _invalidate_review_badge_schema_cache()


settings.change.connect(_on_settings_changed)


def get_review_badge_specs() -> tuple[ReviewBadgeSpec, ...]:
    global _review_badge_specs_cache
    if _review_badge_specs_cache is not None:
        return _review_badge_specs_cache

    overrides = _load_badge_schema_overrides()
    _review_badge_specs_cache = tuple(
        _build_badge_spec(default_row, overrides.get(str(default_row['badge_id'])))
        for default_row in _DEFAULT_BADGE_ROWS
    )
    return _review_badge_specs_cache


def get_review_badge_spec_for_id(badge_id: str) -> ReviewBadgeSpec | None:
    target = str(badge_id or '').strip()
    if not target:
        return None
    for spec in get_review_badge_specs():
        if spec.badge_id == target:
            return spec
    return None


def get_review_badge_spec_for_rank(rank: int) -> ReviewBadgeSpec | None:
    normalized_rank = normalize_review_rank(rank)
    if not normalized_rank:
        return None
    for spec in get_review_badge_specs():
        if spec.kind == 'rank' and int(spec.rank or 0) == int(normalized_rank):
            return spec
    return None


def get_review_badge_spec_for_flag(flag_value) -> ReviewBadgeSpec | None:
    if isinstance(flag_value, str):
        normalized_flag = parse_review_flag_token(flag_value)
    else:
        normalized_flag = ReviewFlag(int(flag_value)) if int(normalize_review_flags(flag_value) or 0) else ReviewFlag.NONE
    if normalized_flag == ReviewFlag.NONE:
        return None
    for spec in get_review_badge_specs():
        if spec.kind == 'flag' and spec.flag == normalized_flag:
            return spec
    return None


def serialize_review_badge_schema() -> list[dict]:
    return [
        {
            'badge_id': spec.badge_id,
            'label': spec.label,
            'title': spec.title,
            'color': spec.color,
            'shortcuts': list(spec.shortcuts),
        }
        for spec in get_review_badge_specs()
    ]


def save_review_badge_schema(raw_rows: list[dict]):
    rows = raw_rows if isinstance(raw_rows, list) else []
    settings.setValue(REVIEW_BADGE_SCHEMA_SETTINGS_KEY, json.dumps(rows, ensure_ascii=True))


def reset_review_badge_schema():
    settings.setValue(REVIEW_BADGE_SCHEMA_SETTINGS_KEY, '')


def get_review_shortcut_action(sequence_text: str):
    normalized = _normalize_shortcut_token(sequence_text)
    if not normalized:
        return None
    lowered = normalized.casefold()
    for spec in get_review_badge_specs():
        if lowered not in {shortcut.casefold() for shortcut in spec.shortcuts}:
            continue
        if spec.kind == 'rank':
            return ('rank', int(spec.rank or 0))
        if spec.kind == 'flag':
            return ('flag', str(spec.flag_name or ''))
    return None


def get_review_badge_text_color() -> str:
    raw_value = settings.value(
        REVIEW_BADGE_TEXT_COLOR_SETTINGS_KEY,
        defaultValue=DEFAULT_REVIEW_BADGE_TEXT_COLOR,
        type=str,
    )
    return _normalize_badge_color(raw_value, DEFAULT_REVIEW_BADGE_TEXT_COLOR)


def get_review_badge_font_size() -> int:
    raw_value = settings.value(
        REVIEW_BADGE_FONT_SIZE_SETTINGS_KEY,
        defaultValue=DEFAULT_REVIEW_BADGE_FONT_SIZE,
        type=int,
    )
    try:
        return max(8, min(24, int(raw_value)))
    except Exception:
        return DEFAULT_REVIEW_BADGE_FONT_SIZE


def get_review_badge_corner_radius() -> int:
    raw_value = settings.value(
        REVIEW_BADGE_CORNER_RADIUS_SETTINGS_KEY,
        defaultValue=DEFAULT_REVIEW_BADGE_CORNER_RADIUS,
        type=int,
    )
    try:
        return max(2, min(14, int(raw_value)))
    except Exception:
        return DEFAULT_REVIEW_BADGE_CORNER_RADIUS
