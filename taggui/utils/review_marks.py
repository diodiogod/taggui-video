from enum import IntFlag


MAX_REVIEW_RANK = 5


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

REVIEW_FLAG_LABELS: dict[ReviewFlag, str] = {
    ReviewFlag.IDEA: 'I',
    ReviewFlag.WARNING: '!',
    ReviewFlag.QUESTION: '?',
    ReviewFlag.REJECT: 'X',
}

REVIEW_FLAG_ALIASES: dict[str, ReviewFlag] = {
    'i': ReviewFlag.IDEA,
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
