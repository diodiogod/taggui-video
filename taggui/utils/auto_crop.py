"""Conservative crop generation for avoiding detected regions."""

from __future__ import annotations

from math import ceil, floor

from PySide6.QtCore import QRect


def calculate_crop_avoiding_boxes(
    dimensions: tuple[int, int] | None,
    boxes: list[list[float]],
    *,
    padding_percent: float = 1.0,
    minimum_retained_percent: float = 75.0,
) -> QRect | None:
    """Return the largest conservative crop that avoids every supplied box.

    Candidate crops remain anchored to at least one image edge. This makes the
    operation useful for edge and corner watermarks without inventing arbitrary
    interior crops. A result is rejected when it retains too little image area.
    """
    if not dimensions or len(dimensions) < 2:
        return None
    width, height = int(dimensions[0]), int(dimensions[1])
    if width <= 0 or height <= 0 or not boxes:
        return None

    padding = max(
        0,
        round(min(width, height) * max(0.0, float(padding_percent)) / 100.0),
    )
    forbidden: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if len(box) != 4:
            continue
        left = max(0, floor(min(float(box[0]), float(box[2]))) - padding)
        top = max(0, floor(min(float(box[1]), float(box[3]))) - padding)
        right = min(width, ceil(max(float(box[0]), float(box[2]))) + padding)
        bottom = min(height, ceil(max(float(box[1]), float(box[3]))) + padding)
        if right > left and bottom > top:
            forbidden.append((left, top, right, bottom))
    if not forbidden:
        return None

    x_starts = sorted({0, *(right for _left, _top, right, _bottom in forbidden)})
    x_ends = sorted({width, *(left for left, _top, _right, _bottom in forbidden)})
    y_starts = sorted({0, *(bottom for _left, _top, _right, bottom in forbidden)})
    y_ends = sorted({height, *(top for _left, top, _right, _bottom in forbidden)})

    candidates: set[tuple[int, int, int, int]] = set()
    # One- or two-sided horizontal/vertical trims.
    candidates.update(
        (x0, 0, x1, height)
        for x0 in x_starts
        for x1 in x_ends
        if x1 > x0
    )
    candidates.update(
        (0, y0, width, y1)
        for y0 in y_starts
        for y1 in y_ends
        if y1 > y0
    )
    # Adjacent-edge trims cover corner watermark combinations without the
    # explosive search space of every possible four-sided rectangle.
    for x0 in x_starts:
        for y0 in y_starts:
            candidates.add((x0, y0, width, height))
        for y1 in y_ends:
            candidates.add((x0, 0, width, y1))
    for x1 in x_ends:
        for y0 in y_starts:
            candidates.add((0, y0, x1, height))
        for y1 in y_ends:
            candidates.add((0, 0, x1, y1))

    full_area = width * height
    minimum_area = full_area * max(
        0.0,
        min(100.0, float(minimum_retained_percent)),
    ) / 100.0

    def intersects_forbidden(candidate: tuple[int, int, int, int]) -> bool:
        left, top, right, bottom = candidate
        return any(
            left < box_right
            and right > box_left
            and top < box_bottom
            and bottom > box_top
            for box_left, box_top, box_right, box_bottom in forbidden
        )

    valid = [
        candidate
        for candidate in candidates
        if (candidate[2] - candidate[0]) * (candidate[3] - candidate[1])
        >= minimum_area
        and not intersects_forbidden(candidate)
    ]
    if not valid:
        return None

    # Maximize retained pixels. Stable secondary terms prefer centered crops
    # and then smaller positional shifts when areas are equal.
    best = max(
        valid,
        key=lambda rect: (
            (rect[2] - rect[0]) * (rect[3] - rect[1]),
            -abs((rect[0] + rect[2]) - width),
            -abs((rect[1] + rect[3]) - height),
            -rect[0] - rect[1],
        ),
    )
    return QRect(
        best[0],
        best[1],
        best[2] - best[0],
        best[3] - best[1],
    )
