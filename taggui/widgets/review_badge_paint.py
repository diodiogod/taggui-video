"""Shared chip painting for thumbnails and positioned review stickers."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPen, QPainterPath


def _color_with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result

def _blend_colors(first: QColor, second: QColor, ratio: float, alpha: int | None = None) -> QColor:
    ratio = max(0.0, min(1.0, float(ratio)))
    mixed = QColor(
        int(first.red() * (1.0 - ratio) + second.red() * ratio),
        int(first.green() * (1.0 - ratio) + second.green() * ratio),
        int(first.blue() * (1.0 - ratio) + second.blue() * ratio),
        int(first.alpha() * (1.0 - ratio) + second.alpha() * ratio),
    )
    if alpha is not None:
        mixed.setAlpha(max(0, min(255, int(alpha))))
    return mixed

def _review_badge_palette(base_color: QColor, style_spec: dict) -> tuple[QColor, QColor]:
    fill_mode = str(style_spec.get('fill_mode', 'base') or 'base')
    if fill_mode == 'dark':
        fill = QColor(style_spec.get('dark_fill', QColor(27, 30, 37, 236)))
    elif fill_mode == 'base_soft':
        fill = QColor(base_color)
        fill.setAlpha(int(style_spec.get('fill_alpha', 120)))
    elif fill_mode == 'warm_base':
        fill = _blend_colors(
            QColor(base_color),
            QColor(style_spec.get('warm_tint', QColor(255, 162, 102, 255))),
            float(style_spec.get('warm_ratio', 0.16)),
            alpha=QColor(base_color).alpha(),
        )
    else:
        fill = QColor(base_color)

    if str(style_spec.get('outline_mode', 'fixed') or 'fixed') == 'base':
        outline = _color_with_alpha(QColor(base_color), int(style_spec.get('outline_alpha', 230)))
    else:
        outline = QColor(style_spec.get('outline', QColor(255, 255, 255, 235)))
    return fill, outline

def draw_overlay_chip(
    painter,
    rect: QRect,
    *,
    fill: QColor,
    outline: QColor,
    radius: float,
    shadow: QColor,
    variant: str = 'solid',
    glass_highlight: QColor | None = None,
    text: str | None = None,
    text_color: QColor | None = None,
    path: QPainterPath | None = None,
    icon_color: QColor | None = None,
):
    shadow_rect = rect.translated(1, 1)
    shadow_pen = QColor(0, 0, 0, min(255, shadow.alpha() + 6))
    painter.setPen(QPen(shadow_pen, 1.1))
    painter.setBrush(shadow)
    painter.drawRoundedRect(shadow_rect, radius, radius)
    painter.setPen(QPen(outline, 1.1))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, radius, radius)

    if variant == 'glass':
        highlight = QRect(
            rect.left() + 1,
            rect.top() + 1,
            max(6, rect.width() - 2),
            max(4, int(rect.height() * 0.45)),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(glass_highlight or QColor(255, 255, 255, 68)))
        painter.drawRoundedRect(highlight, max(3.0, radius - 2.0), max(3.0, radius - 2.0))

    if path is not None and icon_color is not None:
        painter.setPen(
            QPen(
                icon_color,
                1.3,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(icon_color)
        painter.drawPath(path)
        return

    if text is not None and text_color is not None:
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

def draw_review_badge(painter, rect, label, base_color, style, radius, text_color):
    fill, outline = _review_badge_palette(base_color, style)
    draw_overlay_chip(
        painter,
        rect,
        fill=fill,
        outline=outline,
        radius=radius,
        shadow=QColor(style.get('shadow', QColor(0, 0, 0, 60))),
        variant=str(style.get('variant', 'solid') or 'solid'),
        glass_highlight=style.get('glass_highlight'),
        text=label,
        text_color=text_color,
    )
