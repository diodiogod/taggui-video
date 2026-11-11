"""Export editable SVG diagrams and PNGs in the existing user-guide style.

Run: venv/Scripts/python.exe scripts/render_sticker_guide_illustrations.py
Only Qt's SVG renderer is loaded; no application services or settings are used.
"""

import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFontDatabase, QGuiApplication

import render_wall_guide_illustrations as guide


def plot(figure, x, y, width, height):
    figure.rect(x, y, width, height, '#e9f1fa', 10, '#c4d3e5')
    gap = width * .018
    cell_width = (width - gap * 5) / 4
    cell_height = (height - gap * 3) / 2
    colors = ('#299ca8', '#8861c1', '#4386d4', '#db776a')
    for row in range(2):
        for column in range(4):
            left = x + gap + column * (cell_width + gap)
            top = y + gap + row * (cell_height + gap)
            figure.rect(left, top, cell_width, cell_height, '#ffffff', 4)
            ax, ay = left + cell_width * .14, top + cell_height * .82
            figure.add(
                f'<path d="M{ax},{top + cell_height * .14} V{ay} H{left + cell_width * .89}" '
                f'fill="none" stroke="#a9bbd1" stroke-width="{max(1, width * .0015)}"/>'
            )
            figure.add(
                f'<path d="M{ax},{ay - cell_height * .10} '
                f'C{left + cell_width * .36},{top + cell_height * .76} '
                f'{left + cell_width * .43},{top + cell_height * .17} '
                f'{left + cell_width * .59},{top + cell_height * .28} '
                f'S{left + cell_width * .77},{top + cell_height * .70} '
                f'{left + cell_width * .88},{top + cell_height * .41}" '
                f'fill="none" stroke="{colors[column]}" stroke-width="{max(1.5, width * .003)}"/>'
            )


def badge(figure, x, y, label, color, size=44):
    figure.rect(x - size / 2, y - size / 2 + 3, size, size, '#12233b', 8)
    figure.rect(x - size / 2, y - size / 2, size, size, color, 8, '#ffffff', 3)
    figure.text(x, y + size * .26, label, size * .72, '#ffffff', 700, 'middle')


def image_and_badge():
    figure = guide.Illustration(
        'Place review stickers on image details',
        'Illustrated example: positions belong to the main image; the thumbnail keeps its fixed review badges.',
        900,
    )
    figure.rect(44, 150, 954, 560, '#ffffff', 16, '#d6e0ec')
    figure.rect(1024, 150, 468, 560, '#ffffff', 16, '#d6e0ec')
    figure.text(72, 192, 'MAIN VIEWER', 19, '#52657d', 700)
    figure.text(1052, 192, 'IMAGE LIST / MASONRY THUMBNAIL', 19, '#52657d', 700)
    plot(figure, 72, 218, 898, 390)
    badge(figure, 206, 352, '1', '#ffc107')
    badge(figure, 460, 355, '3', '#22c55e')
    badge(figure, 690, 505, '3', '#22c55e')
    badge(figure, 865, 344, '!', '#f59e0b')
    figure.add('<path d="M714,520 l0,34 l9,-9 l8,15 l7,-4 l-8,-14 l12,-1 Z" '
               'fill="#ffffff" stroke="#12233b" stroke-width="2"/>')
    figure.text(74, 653, 'Place 1, then 3. Mark another detail with 3 or !.', 23, weight=700)
    figure.text(74, 685, 'Each sticker keeps its own position on the image.', 21, '#52657d')
    plot(figure, 1052, 218, 412, 240)
    badge(figure, 1081, 245, '3', '#22c55e', 36)
    badge(figure, 1125, 245, '!', '#f59e0b', 36)
    figure.text(1054, 496, 'plot.png', 24, weight=700)
    figure.text(1054, 539, 'Current numeric rank: 3', 22)
    figure.text(1054, 575, 'Warning is also enabled.', 22)
    figure.text(1054, 642, 'One fixed badge per active type.', 20, '#52657d')
    figure.text(1054, 678, 'No positioned thumbnail stickers.', 20, '#52657d')
    figure.rect(44, 742, 1448, 112, '#e4edf8', 14)
    figure.text(72, 782, 'Clear a badge to remove its matching stickers.', 25, weight=700)
    figure.text(72, 820, 'Turn rank 3 off outside the main image: the 3 stickers disappear, and the remaining 1 supplies rank 1.', 22)
    figure.save('sticker-image-and-badge')


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    font_root = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('arial.ttf', 'arialbd.ttf'):
        path = font_root / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.families()
    guide.FONT_FAMILY = next((name for name in ('Arial', 'DejaVu Sans', 'Liberation Sans')
                              if name in families), None)
    if guide.FONT_FAMILY is None:
        raise RuntimeError('A readable sans-serif font is required to export these illustrations.')
    guide.OUTPUT.mkdir(parents=True, exist_ok=True)
    image_and_badge()
    return app


if __name__ == '__main__':
    main()
