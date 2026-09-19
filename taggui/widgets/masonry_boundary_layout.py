"""Bidirectional masonry around a fixed jump boundary (worker-only math)."""

import math


def calculate_boundary_layout(items_data, width, spacing, columns, boundary):
    start, origin, average = boundary
    entries = sorted((int(i), ar) for i, ar in items_data if i >= 0 and not isinstance(ar, tuple))
    result = []

    def place(entries, upward):
        heights = [float(origin)] * columns
        previous = start if upward else start - 1
        for index, ratio in entries:
            gap = previous - index - 1 if upward else index - previous - 1
            if gap > 0:
                extent = math.ceil(gap / columns) * average
                level = min(heights) - extent if upward else max(heights) + extent
                heights = [level] * columns
            ratio = ratio if isinstance(ratio, (float, int)) and math.isfinite(ratio) and ratio > 0 else 1.0
            height = max(1, int(width / max(.01, min(100., ratio))))
            col = max(range(columns), key=heights.__getitem__) if upward else min(range(columns), key=heights.__getitem__)
            y = int(heights[col] - spacing - height) if upward else int(heights[col])
            result.append(dict(index=index, x=col * (width + spacing), y=y,
                               width=width, height=height, aspect_ratio=ratio))
            heights[col] = y if upward else y + height + spacing
            previous = index

    place([entry for entry in entries if entry[0] >= start], False)
    place(list(reversed([entry for entry in entries if entry[0] < start])), True)
    # If actual upper content outgrows its estimate, translate the whole
    # coordinate system; relative positions and the straight boundary survive.
    shift = max(0, -min((item['y'] for item in result), default=0))
    for item in result:
        item['y'] += shift
    result.sort(key=lambda item: item['index'])
    top = min((item['y'] for item in result), default=0)
    if top > 0:
        result.insert(0, dict(index=-2, x=0, y=0, width=columns * (width + spacing) - spacing,
                              height=top, aspect_ratio=1.0))
    return dict(items=result, total_height=max((it['y'] + it['height'] for it in result), default=0),
                boundary_origin=origin + shift)
