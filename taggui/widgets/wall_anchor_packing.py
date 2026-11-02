"""Packing around immovable obstacles; all coordinates are screen coordinates."""
import math
from PySide6.QtCore import QRect


def subtract(free, obstacle):
    result = []
    for r in free:
        if not r.intersects(obstacle):
            result.append(r)
            continue
        for piece in (
            QRect(r.x(), r.y(), obstacle.x() - r.x(), r.height()),
            QRect(obstacle.right() + 1, r.y(), r.right() - obstacle.right(), r.height()),
            QRect(r.x(), r.y(), r.width(), obstacle.y() - r.y()),
            QRect(r.x(), obstacle.bottom() + 1, r.width(), r.bottom() - obstacle.bottom()),
        ):
            if piece.isValid() and r.contains(piece):
                result.append(piece)
    unique = list({(r.x(), r.y(), r.width(), r.height()): r for r in result}.values())
    return [r for i, r in enumerate(unique) if not any(
        j != i and other.contains(r) for j, other in enumerate(unique))]


def pack_anchored_wall(ratios, bounds, anchors, *, spacing=6, preferred_sizes=None,
                       fixed_sizes=None, minimum_sizes=None, automatic_sizing=True,
                       previous_rects=None, cancelled=None, anchor_preview=False):
    from widgets.floating_wall_packing import WallPackingResult, valid_layout
    count, gap = len(ratios), max(0, int(spacing))
    empty = WallPackingResult([], 'Anchored')
    if len(anchors) != count or not bounds.isValid():
        return empty
    # User-positioned anchors may extend beyond the work area. Only movable
    # windows must fit inside it. Keep anchor geometry exact while subtract()
    # naturally clips their occupied area to the on-screen free rectangles.
    anchor_rects = [r for r in anchors if r is not None]
    validation_bounds = QRect(bounds)
    for rect in anchor_rects:
        validation_bounds = validation_bounds.united(rect)
    if not valid_layout(anchor_rects, validation_bounds, gap):
        return empty
    previous = previous_rects or [QRect(bounds.topLeft(), bounds.size())] * count
    seeds = preferred_sizes or [(max(24, r.width()), max(24, r.height())) for r in previous]
    fixed = fixed_sizes or [None] * count
    minimum = minimum_sizes or [(24, 24)] * count
    movable = [i for i in range(count) if anchors[i] is None]
    initial = [bounds.adjusted(0, 0, gap, gap)]
    for anchor in anchors:
        if anchor is not None:
            initial = subtract(initial, anchor.adjusted(0, 0, gap, gap))
    best, score = [], None
    orders = [movable, sorted(movable, key=lambda i: -seeds[i][0] * seeds[i][1]),
              sorted(movable, key=lambda i: (fixed[i] is None, -seeds[i][0] * seeds[i][1]))]
    def evaluate(scale):
        nonlocal best, score
        feasible = False
        for order in orders:
            free, placed = list(initial), [QRect(r) if r is not None else None for r in anchors]
            for i in order:
                if cancelled is not None and cancelled.is_set():
                    return False
                size = fixed[i] or (seeds[i] if not automatic_sizing else None)
                if size is None:
                    ratio = max(.01, float(ratios[i]))
                    w = math.ceil(max(minimum[i][0], minimum[i][1] * ratio, seeds[i][0] * scale))
                    size = (w, math.ceil(w / ratio))
                w, h = size
                if w < minimum[i][0] or h < minimum[i][1]:
                    break
                candidates = []
                for r in free:
                    if w + gap > r.width() or h + gap > r.height():
                        continue
                    x = min(max(previous[i].x(), r.x()), r.right() + 1 - w - gap)
                    y = min(max(previous[i].y(), r.y()), r.bottom() + 1 - h - gap)
                    for px, py in [(x, y), (r.x(), r.y()), (r.right()+1-w-gap, r.y()),
                                   (r.x(), r.bottom()+1-h-gap)]:
                        candidate = QRect(px, py, w, h)
                        distance = (candidate.center() - previous[i].center()).manhattanLength()
                        candidates.append((distance, r.width()*r.height(), candidate))
                if not candidates:
                    break
                rect = min(candidates, key=lambda c: c[:2])[2]
                placed[i] = rect
                free = subtract(free, rect.adjusted(0, 0, gap, gap))
            if (any(r is None for r in placed)
                    or not valid_layout(placed, validation_bounds, gap)
                    or any(not bounds.contains(placed[i]) for i in movable)):
                continue
            feasible = True
            area = sum(r.width()*r.height() for r in placed)
            movement = sum((r.center()-old.center()).manhattanLength() for r, old in zip(placed, previous))
            value = (area, -movement)
            if score is None or value > score:
                best, score = placed, value
        return feasible

    scalable = [i for i in movable if fixed[i] is None and automatic_sizing]
    if not scalable:
        evaluate(1.0)
    elif anchor_preview:
        # Drag previews preserve sizes whenever possible, avoiding visual churn.
        for scale in [1.0] + [1 - i / 24 for i in range(1, 25)]:
            if cancelled is not None and cancelled.is_set():
                break
            if evaluate(scale):
                break
    else:
        # Resize/repack may grow free windows again. Retain actual candidates:
        # greedy packing feasibility is not guaranteed to be monotonic.
        upper = min(min(bounds.width() / max(1, seeds[i][0]),
                        bounds.height() / max(1, seeds[i][1])) for i in scalable)
        evaluate(1.0)
        highest = 0.0
        for step in range(25):
            if cancelled is not None and cancelled.is_set():
                break
            scale = upper * step / 24
            if evaluate(scale):
                highest = max(highest, scale)
        low, high = highest, min(upper, highest + upper / 24)
        for _ in range(10):
            if cancelled is not None and cancelled.is_set():
                break
            middle = (low + high) / 2
            if evaluate(middle):
                low = middle
            else:
                high = middle
    return WallPackingResult(best, 'Anchored')
