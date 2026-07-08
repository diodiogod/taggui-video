"""Shared compare-divider styling and centered geometry helpers."""

COMPARE_DIVIDER_THICKNESS_PX = 2
COMPARE_DIVIDER_COLOR = "rgba(0, 0, 0, 230)"


def centered_divider_geometry(*, line_pos: int, thickness: int, span: int, vertical: bool) -> tuple[int, int, int, int]:
    """Return centered divider geometry for a vertical or horizontal overlay."""
    thickness_i = max(1, int(thickness))
    span_i = max(1, int(span))
    origin = max(0, int(line_pos) - (thickness_i // 2))
    if vertical:
        return (origin, 0, thickness_i, span_i)
    return (0, origin, span_i, thickness_i)
