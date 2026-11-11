"""Reaction artwork used by the sticker and its placement transition."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient

from widgets.reaction_feedback_overlay import _bomb_path, _burst_path, _heart_path


def _settling_progress(progress: float) -> float:
    t = max(0.0, min(1.0, (progress - 0.36) / 0.64))
    return t * t * (3.0 - 2.0 * t)


def reaction_sticker_frame_size(final_size: int, kind: str, progress: float) -> int:
    """Shrink the reaction to the saved sticker size around one fixed center."""
    progress = max(0.0, min(1.0, progress))
    settling = _settling_progress(progress)
    initial_size = max(final_size, min(144.0, max(80.0, final_size * 2.8)))
    size = final_size + (initial_size - final_size) * (1.0 - settling)
    if kind == 'love':
        pulse_a = math.sin(min(1.0, progress / 0.20) * math.pi)
        pulse_b = math.sin(max(0.0, min(1.0, (progress - 0.18) / 0.24)) * math.pi)
        size *= 1.0 + 0.10 * min(1.0, pulse_a + 0.92 * pulse_b) * (1.0 - settling)
    return max(1, int(round(size)))


def draw_reaction_sticker_art(
    painter: QPainter, rect: QRectF, kind: str, *, progress: float = 1.0,
):
    """Draw one reaction; the last animation frame is the permanent sticker."""
    kind = str(kind or '').strip().lower()
    if kind not in {'love', 'bomb'}:
        return
    rect = QRectF(rect)
    side = min(rect.width(), rect.height())
    if side <= 0.0:
        return
    progress = max(0.0, min(1.0, progress))
    motion = 1.0 - _settling_progress(progress)
    center = rect.center()
    accent = QColor(255, 112, 140) if kind == 'love' else QColor(255, 170, 92)
    glow = QRadialGradient(center, side * 0.56)
    glow_alpha = int(115 + 60 * math.sin(progress * math.pi) * motion)
    glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), glow_alpha))
    glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(center, side * 0.56, side * 0.56)

    if kind == 'love':
        heart_rect = QRectF(
            rect.left() + rect.width() * 0.02,
            rect.top() + rect.height() * 0.155,
            rect.width() * 0.96,
            rect.height() * 0.69,
        )
        heart = _heart_path(heart_rect)
        painter.save()
        painter.translate(0.0, side * 0.02)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(92, 23, 43, 125))
        painter.drawPath(heart)
        painter.restore()
        painter.setPen(QPen(QColor(255, 222, 228, 245), side * 0.045,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(255, 110, 138, 250))
        painter.drawPath(heart)

        highlight = QPainterPath()
        highlight.moveTo(heart_rect.left() + heart_rect.width() * 0.24,
                        heart_rect.top() + heart_rect.height() * 0.30)
        highlight.cubicTo(
            heart_rect.left() + heart_rect.width() * 0.30,
            heart_rect.top() + heart_rect.height() * 0.20,
            heart_rect.left() + heart_rect.width() * 0.40,
            heart_rect.top() + heart_rect.height() * 0.22,
            heart_rect.left() + heart_rect.width() * 0.43,
            heart_rect.top() + heart_rect.height() * 0.31,
        )
        painter.setPen(QPen(QColor(255, 245, 247, 185), side * 0.035,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(highlight)
    else:
        painter.translate(center)
        painter.rotate((-0.8 + 1.6 * progress) * motion)
        painter.translate(-center)
        burst_growth = min(1.0, progress / 0.55) ** 2
        burst_outer = side * (0.48 + (0.18 + 0.30 * burst_growth - 0.48) * motion)
        burst_inner = side * 0.29 + (burst_outer * 0.46 - side * 0.29) * motion
        burst = _burst_path(
            center, burst_inner, burst_outer, points=8,
            rotation_deg=-90.0 + 45.0 * progress * motion,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 136, 52, 225))
        painter.drawPath(burst)

        for ring_index in range(2):
            final_radius = side * (0.31 + ring_index * 0.115)
            ring_drive = max(0.0, min(1.0, progress / 0.60 - ring_index * 0.20))
            ring_radius = final_radius + (side * (0.18 + 0.36 * ring_drive) - final_radius) * motion
            final_alpha = 190 - ring_index * 38
            ring_alpha = int(final_alpha + (205 * (1.0 - ring_drive * 0.88) - final_alpha) * motion)
            ring_color = QColor(255, 178, 92, ring_alpha)
            painter.setPen(QPen(ring_color, side * (0.035 - ring_index * 0.006)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, ring_radius, ring_radius)

        spark_center = QPointF(rect.right() - side * 0.16, rect.top() + side * 0.16)
        spark_pulse = math.sin(min(1.0, progress / 0.35) * math.pi) * motion
        spark = _burst_path(spark_center, side * 0.045, side * (0.11 + 0.055 * spark_pulse), points=5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 234, 164, 250))
        painter.drawPath(spark)

        bomb_rect = rect.adjusted(side * 0.08, side * 0.08, -side * 0.08, -side * 0.08)
        bomb = _bomb_path(bomb_rect)
        painter.setPen(QPen(QColor(255, 224, 186, 250), side * 0.045,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(42, 44, 52, 250))
        painter.drawPath(bomb)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 241, 207, 210))
        painter.drawEllipse(
            QPointF(center.x() - side * 0.075, center.y() - side * 0.045),
            side * 0.033,
            side * 0.033,
        )
    painter.restore()


