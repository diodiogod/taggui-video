"""Masonry-style layout planner for floating viewer walls."""

from __future__ import annotations

from PySide6.QtCore import QRect


def _normalized_aspect_ratio(value: float | None) -> float:
    """Clamp media ratios to avoid unusably tall or flat floating windows."""
    try:
        ratio = float(value or 0.0)
    except Exception:
        ratio = 0.0
    if ratio <= 0.0:
        ratio = 1.0
    return max(1.0 / 3.0, min(3.0, ratio))


def _layout_candidate(
    aspect_ratios: list[float],
    available_rect: QRect,
    *,
    spacing: int,
    columns: int,
    min_item_width: int,
    min_item_height: int,
) -> tuple[list[QRect], float] | None:
    if columns <= 0 or not aspect_ratios or not available_rect.isValid():
        return None

    available_width = max(1, int(available_rect.width()))
    available_height = max(1, int(available_rect.height()))
    spacing = max(0, int(spacing))

    base_column_width = (available_width - (spacing * max(0, columns - 1))) / float(columns)
    if base_column_width <= 0:
        return None

    # First pass: compute the unscaled masonry height with shortest-column placement.
    raw_column_heights = [0.0 for _ in range(columns)]
    for ratio in aspect_ratios:
        column_index = min(range(columns), key=lambda idx: (raw_column_heights[idx], idx))
        item_height = base_column_width / _normalized_aspect_ratio(ratio)
        raw_column_heights[column_index] += item_height + spacing

    raw_total_height = max(raw_column_heights) - spacing if raw_column_heights else 0.0
    if raw_total_height <= 0:
        return None

    scale = min(1.0, available_height / raw_total_height)
    final_spacing = max(4, int(round(spacing * scale))) if spacing > 0 else 0
    column_width = int(base_column_width * scale)
    if column_width < int(min_item_width):
        return None

    column_heights = [0 for _ in range(columns)]
    rects: list[QRect] = []
    for ratio in aspect_ratios:
        column_index = min(range(columns), key=lambda idx: (column_heights[idx], idx))
        item_height = int(round(column_width / _normalized_aspect_ratio(ratio)))
        item_height = max(int(min_item_height), item_height)
        x = column_index * (column_width + final_spacing)
        y = column_heights[column_index]
        rects.append(QRect(x, y, column_width, item_height))
        column_heights[column_index] += item_height + final_spacing

    total_height = max((rect.bottom() + 1) for rect in rects) if rects else 0
    if total_height > available_height and total_height > 0:
        shrink = available_height / float(total_height)
        column_width = int(column_width * shrink)
        final_spacing = max(2, int(round(final_spacing * shrink))) if final_spacing > 0 else 0
        if column_width < int(min_item_width):
            return None
        column_heights = [0 for _ in range(columns)]
        rects = []
        for ratio in aspect_ratios:
            column_index = min(range(columns), key=lambda idx: (column_heights[idx], idx))
            item_height = int(round(column_width / _normalized_aspect_ratio(ratio)))
            item_height = max(int(min_item_height), item_height)
            x = column_index * (column_width + final_spacing)
            y = column_heights[column_index]
            rects.append(QRect(x, y, column_width, item_height))
            column_heights[column_index] += item_height + final_spacing

    used_width = 0
    if rects:
        used_width = max((rect.right() + 1) for rect in rects)
    offset_x = int(available_rect.left()) + max(0, (available_width - used_width) // 2)
    offset_y = int(available_rect.top())
    translated = [rect.translated(offset_x, offset_y) for rect in rects]
    total_area = float(sum(rect.width() * rect.height() for rect in translated))
    return translated, total_area


def calculate_floating_viewer_wall_layout(
    aspect_ratios: list[float],
    available_rect: QRect,
    *,
    spacing: int = 12,
    min_item_width: int = 180,
    min_item_height: int = 120,
    max_columns: int | None = None,
) -> list[QRect]:
    """Return top-aligned masonry rects sized to fill the current screen."""
    if not aspect_ratios or not available_rect.isValid():
        return []

    available_width = max(1, int(available_rect.width()))
    spacing = max(0, int(spacing))
    min_item_width = max(80, int(min_item_width))
    min_item_height = max(80, int(min_item_height))

    natural_max_columns = max(
        1,
        int((available_width + spacing) / max(1, min_item_width + spacing)),
    )
    if max_columns is None:
        max_columns = natural_max_columns
    else:
        max_columns = max(1, min(int(max_columns), natural_max_columns))
    max_columns = min(max_columns, len(aspect_ratios))

    best_layout: list[QRect] | None = None
    best_area = -1.0

    for columns in range(1, max_columns + 1):
        candidate = _layout_candidate(
            aspect_ratios,
            available_rect,
            spacing=spacing,
            columns=columns,
            min_item_width=min_item_width,
            min_item_height=min_item_height,
        )
        if not candidate:
            continue
        rects, area = candidate
        if area > best_area:
            best_layout = rects
            best_area = area

    if best_layout is None and (min_item_width > 80 or min_item_height > 80):
        relaxed_columns = min(len(aspect_ratios), max(1, int((available_width + spacing) / max(1, 80 + spacing))))
        for columns in range(1, max(1, relaxed_columns) + 1):
            candidate = _layout_candidate(
                aspect_ratios,
                available_rect,
                spacing=spacing,
                columns=columns,
                min_item_width=80,
                min_item_height=80,
            )
            if not candidate:
                continue
            rects, area = candidate
            if area > best_area:
                best_layout = rects
                best_area = area

    if best_layout is not None:
        return best_layout

    columns = max(1, min(len(aspect_ratios), max_columns))
    cell_width = max(80, int((available_rect.width() - (spacing * max(0, columns - 1))) / max(1, columns)))
    cell_height = max(80, cell_width)
    rects = []
    for index in range(len(aspect_ratios)):
        row = index // columns
        column = index % columns
        x = int(available_rect.left()) + (column * (cell_width + spacing))
        y = int(available_rect.top()) + (row * (cell_height + spacing))
        rects.append(QRect(x, y, cell_width, cell_height))
    return rects
