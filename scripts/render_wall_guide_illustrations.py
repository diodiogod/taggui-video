"""Rebuild the editable SVG diagrams and their PNG documentation exports.

Uses Qt's SVG renderer only; no application services or user settings are loaded.
Run: venv/Scripts/python.exe scripts/render_wall_guide_illustrations.py
"""
from html import escape
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


OUTPUT = Path(__file__).resolve().parents[1] / 'images' / 'guides'
INK, MUTED = '#12233b', '#52657d'
FONT_FAMILY = 'Arial'
COLORS = {'A': '#299ca8', 'B': '#8861c1', 'C': '#4386d4', 'D': '#db776a'}


class Illustration:
    def __init__(self, title, subtitle, height=960):
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="{height}" viewBox="0 0 1536 {height}">',
            f'<rect width="1536" height="{height}" fill="#f6f8fc"/>',
        ]
        self.text(44, 70, title, 40, weight=700)
        self.text(44, 108, subtitle, 21, MUTED)
        self.serial = 0

    def add(self, markup):
        self.parts.append(markup)

    def text(self, x, y, value, size=22, color=INK, weight=400, anchor='start'):
        self.add(f'<text x="{x}" y="{y}" font-family="{FONT_FAMILY}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(value)}</text>')

    def rect(self, x, y, w, h, fill, radius=12, stroke=None, width=2):
        outline = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ''
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"{outline}/>')

    def screen(self, x, y, w, h):
        self.rect(x, y, w, h, '#152b42', 18)
        self.text(x + 18, y + 26, 'SCREEN AREA', 13, '#acc0d6', 700)

    def media(self, origin, name, box, *, kept=False, resizing=False):
        """Illustrate the media inside exact, undistorted window rectangles."""
        x, y, w, h = box
        x += origin[0]
        y += origin[1]
        self.serial += 1
        clip = f'media{self.serial}'
        self.add(f'<defs><clipPath id="{clip}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/></clipPath></defs>')
        self.add(f'<g clip-path="url(#{clip})">')
        self.rect(x, y, w, h, COLORS[name], 8)
        self.add(f'<circle cx="{x + w * .78}" cy="{y + h * .3}" r="{min(w, h) * .12}" fill="#ffe7b1"/>')
        self.add(f'<path d="M{x},{y+h} L{x},{y+h*.68} L{x+w*.28},{y+h*.35} L{x+w*.57},{y+h*.74} L{x+w*.8},{y+h*.5} L{x+w},{y+h*.76} L{x+w},{y+h} Z" fill="#142944" fill-opacity=".4"/>')
        self.add(f'<path d="M{x},{y+h} L{x},{y+h*.86} L{x+w*.18},{y+h*.65} L{x+w*.52},{y+h*.88} L{x+w*.73},{y+h*.62} L{x+w},{y+h*.92} L{x+w},{y+h} Z" fill="#102137" fill-opacity=".38"/>')
        self.add('</g>')
        self.text(x + 11, y + 28, name, 24, '#ffffff', 700)
        if name in ('B', 'D'):
            cx, cy = x + w / 2, y + h / 2
            self.add(f'<path d="M{cx-7},{cy-10} L{cx+10},{cy} L{cx-7},{cy+10} Z" fill="#ffffff" fill-opacity=".8"/>')
        if kept or resizing:
            self.rect(x, y, w, h, 'none', 8, '#ffc45a', 4)
        if kept:
            lx, ly = x + w - 27, y + 13
            self.rect(lx, ly + 8, 17, 14, '#ffc45a', 3)
            self.add(f'<path d="M{lx+4},{ly+9} V{ly+5} A4.5,4.5 0 0 1 {lx+13},{ly+5} V{ly+9}" fill="none" stroke="#ffc45a" stroke-width="3"/>')
        if resizing:
            self.rect(x + w - 7, y + h - 7, 14, 14, '#ffc45a', 2)
            self.add(f'<path d="M{x+w+6},{y+h+4} l0,27 l8,-8 l7,13 l6,-3 l-7,-12 l11,-1 Z" fill="#ffffff" stroke="#12233b" stroke-width="2"/>')

    def key(self, x, y, label, width=110, height=64):
        self.rect(x, y + 5, width, height, '#d3dbe8', 12)
        self.rect(x, y, width, height, '#ffffff', 12, '#9aacbf', 2)
        self.text(x + width / 2, y + height / 2 + 10, label, 29, weight=700, anchor='middle')

    def chip(self, x, y, width, label, fill='#e4edf8'):
        self.rect(x, y, width, 44, fill, 22)
        self.text(x + width / 2, y + 29, label, 18, weight=700, anchor='middle')

    def save(self, name):
        source = '\n'.join(self.parts + ['</svg>'])
        svg = OUTPUT / f'{name}.svg'
        png = OUTPUT / f'{name}.png'
        svg.write_text(source, encoding='utf-8')
        renderer = QSvgRenderer(str(svg))
        assert renderer.isValid(), svg
        image = QImage(1536, self.height, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            renderer.render(painter, QRectF(0, 0, 1536, self.height))
        finally:
            painter.end()
        assert image.save(str(png)), png
        print(png)


def resize_reflow():
    figure = Illustration('Resize one window. Reflow the wall.',
                          'Illustrated example. Positions are schematic; proportions and kept sizes are consistent.', 880)
    initial = {'A': (18, 44, 220, 110), 'B': (18, 215, 190, 95),
               'C': (314, 44, 110, 110), 'D': (280, 236, 84, 168)}
    during = dict(initial, A=(18, 44, 290, 145))
    after = {'A': during['A'], 'B': (18, 211, 174, 87),
             'C': (326, 44, 90, 90), 'D': (220, 211, 84, 168)}
    for index, (x, label, boxes) in enumerate(zip((44, 548, 1052),
            ('Start with a wall', 'Resize A', 'Release the mouse'), (initial, during, after))):
        figure.chip(x, 152, 46, str(index + 1))
        figure.text(x + 61, 183, label, 27, weight=700)
        figure.screen(x, 218, 440, 438)
        for name, box in boxes.items():
            figure.media((x, 218), name, box, kept=index == 2 and name == 'A',
                         resizing=index == 1 and name == 'A')
        captions = [('A begins at its original size.', 'B, C and D have different shapes.'),
                    ('Only A changes while you drag.', 'A keeps its landscape proportions.'),
                    ("A's chosen size is kept.", 'Other windows may move or resize.')][index]
        for row, caption in enumerate(captions):
            figure.text(x, 696 + row * 32, caption, 22, weight=700 if row == 0 else 400)
    figure.chip(44, 786, 262, 'Reflow after resizing: ON', '#ddefe9')
    figure.chip(327, 786, 354, 'Preserve manually resized sizes: ON', '#fff0d4')
    figure.chip(702, 786, 330, 'Automatically size other windows: ON')
    figure.text(1490, 856, 'A / B: landscape    C: square    D: portrait', 16, MUTED, anchor='end')
    figure.save('wall-resize-reflow')


def sizing_modes():
    figure = Illustration('Choose what reflow can change.',
                          'Kept window A stays the same size in both modes. All window proportions are preserved.', 1110)
    initial = {'A': (22, 65, 210, 105), 'B': (247, 174, 200, 100),
               'C': (430, 44, 100, 100), 'D': (555, 90, 80, 160)}
    on = {'A': (22, 44, 210, 105), 'B': (246, 44, 156, 78),
          'C': (416, 44, 80, 80), 'D': (510, 44, 60, 120)}
    off = {'A': (22, 44, 210, 105), 'B': (246, 44, 200, 100),
           'C': (246, 158, 100, 100), 'D': (460, 44, 80, 160)}
    for x, mode, after, caption in ((44, 'ON', on, 'Unkept windows may move AND resize.'),
                                   (804, 'OFF', off, 'Windows move. Every current size stays fixed.')):
        figure.text(x, 173, f'Automatic sizing: {mode}', 30, weight=700)
        figure.text(x, 210, caption, 21, MUTED)
        for y, label, boxes in ((266, 'Before repack', initial), (646, 'After repack', after)):
            figure.text(x, y - 14, label, 22, weight=700)
            figure.screen(x, y, 688, 300)
            for name, box in boxes.items():
                figure.media((x, y), name, box, kept=name == 'A')
        figure.text(x, 984, 'A keeps its chosen size.', 22, weight=700)
    figure.rect(44, 1020, 1448, 58, '#fff0d4', 12)
    figure.text(68, 1057, 'If fixed sizes do not fit: keep the current layout and show a brief tooltip. No permanent UI row.', 21)
    figure.save('wall-sizing-options')


def manual_control():
    figure = Illustration('Take manual control.',
                          'Use a one-gesture bypass or leave Manual Wall Layout on for several adjustments.', 850)
    for x in (44, 804):
        figure.rect(x, 160, 688, 608, '#ffffff', 18, '#dce4ee')
    figure.text(76, 211, 'Hold Alt for one gesture', 30, weight=700)
    figure.key(76, 246, 'Alt', 134, 78)
    figure.text(236, 278, '+ drag to move or resize', 23, weight=700)
    figure.text(236, 309, 'Skip automatic reflow for this gesture.', 20, MUTED)
    figure.text(76, 373, 'Only the window you adjust changes.', 24, weight=700)
    figure.text(76, 408, 'Its new size is remembered.', 22, MUTED)
    figure.screen(76, 438, 624, 214)
    for name, box in {'A': (18, 44, 224, 112), 'B': (298, 44, 136, 68),
                      'C': (486, 70, 96, 96)}.items():
        figure.media((76, 438), name, box, resizing=name == 'A')
    figure.text(76, 698, 'Alt may be released before the mouse.', 22, weight=700)
    figure.text(76, 733, 'Moving a window alone never triggers reflow.', 20, MUTED)
    figure.text(836, 211, 'Toggle Manual Wall Layout', 30, weight=700)
    for x, label, width in ((836, 'Ctrl', 136), (1010, 'Alt', 126), (1174, 'M', 94)):
        figure.key(x, 246, label, width, 78)
    figure.text(986, 297, '+', 29, MUTED, anchor='middle')
    figure.text(1154, 297, '+', 29, MUTED, anchor='middle')
    figure.chip(1290, 265, 166, 'Configurable', '#e4edf8')
    figure.text(836, 373, 'Make several adjustments at your own pace.', 23, weight=700)
    figure.text(836, 408, 'Automatic rearrangement stays suspended.', 22, MUTED)
    figure.rect(836, 451, 624, 90, '#e4edf8', 12)
    figure.text(860, 505, 'Manual Wall Layout', 26, weight=700)
    figure.rect(1310, 475, 126, 42, '#158067', 21)
    figure.text(1334, 503, 'ON', 21, '#ffffff', 700)
    figure.add('<circle cx="1413" cy="496" r="15" fill="#ffffff"/>')
    figure.text(836, 584, 'Toggle it off when you are ready.', 24, weight=700)
    figure.text(836, 619, 'Automatic reflow resumes on the next resize.', 22, MUTED)
    figure.text(836, 698, 'Repack current wall works even in manual mode.', 21, weight=700)
    figure.text(836, 733, 'Use the wall menu for a deliberate repack.', 20, MUTED)
    figure.text(44, 818, 'Illustrated examples. Default shortcut: Ctrl+Alt+M. Shift still controls aspect preservation.', 20, MUTED)
    figure.save('wall-manual-controls')


def main():
    global FONT_FAMILY
    app = QGuiApplication.instance() or QGuiApplication([])
    # Qt's offscreen Windows platform does not discover system fonts. Register
    # their installed files explicitly so the exported PNGs contain real text.
    font_root = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('arial.ttf', 'arialbd.ttf'):
        font_path = font_root / filename
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.families()
    FONT_FAMILY = next((name for name in ('Arial', 'DejaVu Sans', 'Liberation Sans')
                        if name in families), None)
    if FONT_FAMILY is None:
        raise RuntimeError('A readable sans-serif font is required to export these illustrations.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    resize_reflow()
    sizing_modes()
    manual_control()
    return app


if __name__ == '__main__':
    main()
