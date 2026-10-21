"""Geometry-only wall packing. Safe to run without viewers or media models."""
from dataclasses import dataclass
import math

from PySide6.QtCore import QRect

from widgets.floating_viewer_wall_layout import calculate_floating_viewer_wall_layout

try:
    from rectpack import MaxRectsBaf, MaxRectsBl, MaxRectsBssf
except ImportError:  # Older portable installations can still use masonry.
    MaxRectsBaf = MaxRectsBl = MaxRectsBssf = None


ALGORITHMS = ('Best fit', 'Masonry', 'MaxRects')


@dataclass
class WallPackingResult:
    rects: list[QRect]
    algorithm: str
    dependency_missing: bool = False


def maxrects_available():
    return MaxRectsBssf is not None


def valid_layout(rects, bounds, spacing=0):
    """Check complete rectangles, screen bounds and the requested clear gap."""
    for index, rect in enumerate(rects):
        if not rect.isValid() or not bounds.contains(rect):
            return False
        padded = rect.adjusted(0, 0, spacing, spacing)
        if any(padded.intersects(other.adjusted(0, 0, spacing, spacing))
               for other in rects[index + 1:]):
            return False
    return True


def _align(rects, bounds, alignment):
    used_width = max(rect.right() + 1 for rect in rects)
    offset = {'left': 0, 'right': bounds.width() - used_width}.get(
        alignment, (bounds.width() - used_width) // 2)
    return [rect.translated(bounds.x() + offset, bounds.y()) for rect in rects]


def _masonry(sizes, width, height, gap, columns):
    """Shortest-column masonry supporting unequal, fixed window widths."""
    heights, widths = [0] * columns, [0] * columns
    placements = []
    for w, h in sizes:
        column = min(range(columns), key=lambda i: (heights[i], i))
        placements.append((column, heights[column], w, h))
        heights[column] += h + gap
        widths[column] = max(widths[column], w)
    if sum(widths) + gap * (columns - 1) > width or max(heights) - gap > height:
        return None
    offsets, x = [], 0
    for w in widths:
        offsets.append(x)
        x += w + gap
    return [QRect(offsets[column], y, w, h) for column, y, w, h in placements]


def _maxrects(sizes, width, height, gap, variant, order):
    packer = variant(width + gap, height + gap, rot=False)
    rects = [None] * len(sizes)
    for index in order:
        w, h = sizes[index]
        placement = packer.add_rect(w + gap, h + gap, rid=index)
        if placement is None:
            return None
        rects[index] = QRect(placement.x, placement.y, w, h)
    return rects


def pack_wall(
    aspect_ratios, bounds, *, algorithm='Best fit', spacing=6,
    horizontal_alignment='center', preferred_sizes=None, fixed_sizes=None,
    minimum_sizes=None, automatic_sizing=True, preserve_order=False,
    previous_rects=None, cancelled=None,
):
    """Find a feasible layout; fixed sizes are hard constraints, never hints.

    Automatic sizing searches a common scale for the remaining windows.
    MaxRects chooses positions only; this search supplies its rectangle sizes.
    Empty results mean no candidate fits and callers must retain the old layout.
    """
    count = len(aspect_ratios)
    missing = not maxrects_available()
    if not count or not bounds.isValid():
        return WallPackingResult([], algorithm, missing)
    if algorithm not in ALGORITHMS:
        algorithm = 'Best fit'
    effective = 'Masonry' if missing else algorithm
    gap = max(0, int(spacing))
    ratios = []
    for value in aspect_ratios:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            ratio = 1.0
        ratios.append(ratio if math.isfinite(ratio) and ratio > 0 else 1.0)
    minimum_sizes = minimum_sizes or [(24, 24)] * count
    fixed_sizes = fixed_sizes or [None] * count
    previous_rects = previous_rects or []
    best, best_score, best_engine = [], None, effective

    def stopped():
        return cancelled is not None and cancelled.is_set()

    def consider(rects, engine):
        nonlocal best, best_score, best_engine
        if rects is None or len(rects) != count:
            return False
        rects = _align(rects, bounds, horizontal_alignment)
        if preserve_order and sorted(range(count), key=lambda i: (rects[i].y(), rects[i].x())) != list(range(count)):
            return False
        if not valid_layout(rects, bounds, gap):
            return False
        for i, rect in enumerate(rects):
            if rect.width() < minimum_sizes[i][0] or rect.height() < minimum_sizes[i][1]:
                return False
            if fixed_sizes[i] is not None and (rect.width(), rect.height()) != tuple(fixed_sizes[i]):
                return False
            if fixed_sizes[i] is None and abs(rect.width() - ratios[i] * rect.height()) > max(1, ratios[i]) + .001:
                return False
        area = sum(r.width() * r.height() for r in rects)
        extent = (max(r.right() for r in rects) - min(r.left() for r in rects) + 1) * (
            max(r.bottom() for r in rects) - min(r.top() for r in rects) + 1)
        movement = sum(abs(a.center().x() - b.center().x()) + abs(a.center().y() - b.center().y())
                       for a, b in zip(rects, previous_rects))
        score = (area, -extent, -movement)
        if best_score is None or score > best_score:
            best, best_score, best_engine = rects, score, engine
        return True

    if preferred_sizes is None:
        legacy = calculate_floating_viewer_wall_layout(
            ratios, QRect(0, 0, bounds.width(), bounds.height()), spacing=gap,
            min_item_width=220 if count <= 8 else 170, min_item_height=120,
            horizontal_alignment='left',
        )
        # Preserve the established masonry candidate when it meets all constraints.
        if effective != 'MaxRects' and not any(fixed_sizes):
            consider(legacy, 'Masonry')
        common_width = math.sqrt(bounds.width() * bounds.height() / sum(1 / r for r in ratios))
        seeds = [[(common_width, common_width / r) for r in ratios]]
        if effective != 'Masonry':
            area = bounds.width() * bounds.height() / count
            seeds.append([(math.sqrt(area * r), math.sqrt(area / r)) for r in ratios])
    else:
        seeds = [preferred_sizes]
        if not automatic_sizing:
            fixed_sizes = [tuple(size) for size in preferred_sizes]

    for seed in seeds:
        if stopped():
            break
        packers = []
        if effective != 'MaxRects':
            for columns in range(1, min(count, 32) + 1):
                packers.append(('Masonry', lambda sizes, c=columns: _masonry(
                    sizes, bounds.width(), bounds.height(), gap, c)))
        if effective != 'Masonry':
            orders = [list(range(count))]
            if not preserve_order:
                orders.extend([
                    sorted(range(count), key=lambda i: -(seed[i][0] * seed[i][1])),
                    sorted(range(count), key=lambda i: -max(seed[i])),
                ])
            for variant in (MaxRectsBssf, MaxRectsBaf, MaxRectsBl):
                for order in dict.fromkeys(tuple(order) for order in orders):
                    packers.append(('MaxRects', lambda sizes, v=variant, o=order: _maxrects(
                        sizes, bounds.width(), bounds.height(), gap, v, o)))

        def sizes_at(scale):
            sizes = []
            for i, (w, h) in enumerate(seed):
                if fixed_sizes[i] is not None:
                    sizes.append(tuple(fixed_sizes[i]))
                else:
                    ratio = ratios[i]
                    width = max(minimum_sizes[i][0], minimum_sizes[i][1] * ratio, w * scale)
                    sizes.append((max(1, int(math.ceil(width))), max(1, int(math.ceil(width / ratio)))))
            return sizes

        scalable = [i for i in range(count) if fixed_sizes[i] is None]
        upper = min((min(bounds.width() / max(1, seed[i][0]),
                         bounds.height() / max(1, seed[i][1])) for i in scalable), default=1.0)
        for engine, pack in packers:
            if stopped():
                break
            # Retain actual successful candidates: heuristic feasibility need not
            # be perfectly monotonic as scale changes the packing choices.
            consider(pack(sizes_at(1.0)), engine)
            if not scalable:
                continue
            low, high = 0.0, upper
            consider(pack(sizes_at(0.0)), engine)
            for _ in range(11):
                if stopped():
                    break
                middle = (low + high) / 2
                if consider(pack(sizes_at(middle)), engine):
                    low = middle
                else:
                    high = middle
    return WallPackingResult(best, best_engine, missing)
