"""Reproducible geometry benchmark: python tests/benchmark_floating_wall_packing.py."""
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from PySide6.QtCore import QRect
from widgets.floating_viewer_wall_layout import calculate_floating_viewer_wall_layout
from widgets.floating_wall_packing import pack_wall, valid_layout


def main():
    rng = random.Random(104)
    cases = [[16 / 9] * 4, [9 / 16] * 6, [1] * 9]
    cases += [rng.choices([.5, 9 / 16, .75, 1, 1.5, 16 / 9, 2], k=n)
              for n in (3, 5, 7, 10, 15, 24) for _ in range(3)]
    bounds = QRect(6, 6, 1908, 1068)
    report = {}
    per_case = []
    for name in ('Original masonry', 'Masonry', 'MaxRects', 'Best fit'):
        coverage, elapsed, invalid = [], [], 0
        for index, ratios in enumerate(cases):
            start = time.perf_counter()
            if name == 'Original masonry':
                rects = calculate_floating_viewer_wall_layout(
                    ratios, bounds, spacing=6, min_item_width=220 if len(ratios) <= 8 else 170)
            else:
                rects = pack_wall(ratios, bounds, algorithm=name).rects
            elapsed.append((time.perf_counter() - start) * 1000)
            fill = sum(r.width() * r.height() for r in rects) / (bounds.width() * bounds.height()) * 100
            coverage.append(fill)
            invalid += int(len(rects) != len(ratios) or not valid_layout(rects, bounds))
            if len(per_case) <= index:
                per_case.append({'count': len(ratios)})
            per_case[index][name] = round(fill, 2)
        report[name] = {'mean_screen_coverage_percent': round(statistics.mean(coverage), 2),
                        'median_ms': round(statistics.median(elapsed), 2),
                        'max_ms': round(max(elapsed), 2), 'invalid_layouts': invalid}
    print(json.dumps({'cases': len(cases), 'summary': report, 'per_case': per_case}, indent=2))


if __name__ == '__main__':
    main()
