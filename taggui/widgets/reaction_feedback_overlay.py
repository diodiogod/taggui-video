import math

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QParallelAnimationGroup,
    QPropertyAnimation,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QTransform
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from widgets.rating_controls import STAR_SHAPE


def _heart_path(rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    w = rect.width()
    h = rect.height()
    path.moveTo(rect.left() + 0.5 * w, rect.bottom() - 0.12 * h)
    path.cubicTo(
        rect.left() + 0.12 * w, rect.top() + 0.62 * h,
        rect.left() + 0.04 * w, rect.top() + 0.24 * h,
        rect.left() + 0.28 * w, rect.top() + 0.16 * h,
    )
    path.cubicTo(
        rect.left() + 0.42 * w, rect.top() + 0.10 * h,
        rect.left() + 0.50 * w, rect.top() + 0.20 * h,
        rect.left() + 0.50 * w, rect.top() + 0.28 * h,
    )
    path.cubicTo(
        rect.left() + 0.50 * w, rect.top() + 0.20 * h,
        rect.left() + 0.58 * w, rect.top() + 0.10 * h,
        rect.left() + 0.72 * w, rect.top() + 0.16 * h,
    )
    path.cubicTo(
        rect.left() + 0.96 * w, rect.top() + 0.24 * h,
        rect.left() + 0.88 * w, rect.top() + 0.62 * h,
        rect.left() + 0.50 * w, rect.bottom() - 0.12 * h,
    )
    path.closeSubpath()
    return path


def _bomb_path(rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    center = rect.center()
    radius = min(rect.width(), rect.height()) * 0.27
    path.addEllipse(center, radius, radius)
    fuse_start = QPointF(center.x() + radius * 0.45, center.y() - radius * 0.85)
    fuse_mid = QPointF(rect.right() - rect.width() * 0.18, rect.top() + rect.height() * 0.20)
    fuse_end = QPointF(rect.right() - rect.width() * 0.10, rect.top() + rect.height() * 0.08)
    path.moveTo(fuse_start)
    path.cubicTo(fuse_mid, fuse_mid, fuse_end)
    path.addEllipse(
        QPointF(center.x() + radius * 0.22, center.y() - radius * 0.12),
        radius * 0.16,
        radius * 0.16,
    )
    return path


def _burst_path(center: QPointF, inner_radius: float, outer_radius: float, points: int = 8, rotation_deg: float = -90.0) -> QPainterPath:
    path = QPainterPath()
    vertices = []
    total_points = max(4, int(points) * 2)
    for point_index in range(total_points):
        angle_deg = float(rotation_deg) + ((360.0 / total_points) * point_index)
        angle_rad = math.radians(angle_deg)
        radius = outer_radius if point_index % 2 == 0 else inner_radius
        vertices.append(
            QPointF(
                center.x() + (radius * math.cos(angle_rad)),
                center.y() + (radius * math.sin(angle_rad)),
            )
        )
    if vertices:
        path.moveTo(vertices[0])
        for point in vertices[1:]:
            path.lineTo(point)
        path.closeSubpath()
    return path


class ReactionFeedbackOverlay(QWidget):
    """Transient animated feedback HUD for reactions and star ratings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()

        self._progress = 0.0
        self._kind = "love"
        self._enabled = True
        self._stars = 0.0
        self._title = "Loved"
        self._anchor_rect = QRect()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._animation_group = QParallelAnimationGroup(self)

        self._progress_animation = QPropertyAnimation(self, b"progress", self)
        self._progress_animation.setDuration(620)
        self._progress_animation.setStartValue(0.0)
        self._progress_animation.setEndValue(1.0)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation_group.addAnimation(self._progress_animation)

        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(620)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setKeyValueAt(0.16, 1.0)
        self._fade_animation.setKeyValueAt(0.72, 1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation_group.addAnimation(self._fade_animation)
        self._animation_group.finished.connect(self._handle_animation_finished)

    def sizeHint(self) -> QSize:
        return QSize(260, 186)

    def minimumSizeHint(self) -> QSize:
        return QSize(190, 138)

    def get_progress(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._progress)))
        except Exception:
            return 0.0

    def set_progress(self, value):
        try:
            progress = float(value)
        except Exception:
            progress = 0.0
        progress = max(0.0, min(1.0, progress))
        if abs(progress - float(getattr(self, "_progress", 0.0) or 0.0)) <= 1e-4:
            return
        self._progress = progress
        self.update()

    progress = Property(float, get_progress, set_progress)

    def _handle_animation_finished(self):
        self.hide()

    def hide_immediately(self):
        self._animation_group.stop()
        self._opacity_effect.setOpacity(0.0)
        self.set_progress(0.0)
        self.hide()

    def reposition(self, anchor_rect: QRect | None = None) -> bool:
        if anchor_rect is not None and isinstance(anchor_rect, QRect) and anchor_rect.isValid():
            self._anchor_rect = QRect(anchor_rect)
        elif anchor_rect is not None:
            self._anchor_rect = QRect()
        parent = self.parentWidget()
        if parent is None:
            return False
        parent_rect = parent.rect()
        if self._anchor_rect.isValid():
            width = min(max(168, int(self._anchor_rect.width() * 1.9)), 238)
            height = min(max(138, int(self._anchor_rect.height() * 2.0)), 210)
            x_pos = int(round(self._anchor_rect.center().x() - (width / 2.0)))
            y_pos = int(round(self._anchor_rect.center().y() - (height * 0.64)))
            x_pos = max(6, min(x_pos, parent_rect.width() - width - 6))
            y_pos = max(6, min(y_pos, parent_rect.height() - height - 6))
        else:
            width = min(max(196, int(parent_rect.width() * 0.34)), 300)
            height = min(max(154, int(parent_rect.height() * 0.28)), 224)
            x_pos = max(8, (parent_rect.width() - width) // 2)
            y_pos = max(28, int(parent_rect.height() * 0.16))
        target = QRect(x_pos, y_pos, width, height)
        if self.geometry() == target:
            return False
        self.setGeometry(target)
        return True

    def show_feedback(
        self,
        kind: str,
        *,
        enabled: bool | None = None,
        stars: float | None = None,
        anchor_rect: QRect | None = None,
    ):
        feedback_kind = str(kind or "").strip().lower()
        if feedback_kind not in {"love", "bomb", "stars"}:
            return
        self._kind = feedback_kind
        if feedback_kind == "stars":
            self._stars = max(0.0, min(5.0, float(stars or 0.0)))
            self._enabled = self._stars > 0.0
            if self._stars <= 0.0:
                self._title = "No Rating"
            elif abs(self._stars - round(self._stars)) <= 1e-6:
                stars_int = int(round(self._stars))
                self._title = f"{stars_int} Star" if stars_int == 1 else f"{stars_int} Stars"
            else:
                self._title = f"{self._stars:.1f} Stars"
        else:
            self._enabled = bool(enabled)
            self._title = {
                ("love", True): "Loved",
                ("love", False): "Love Off",
                ("bomb", True): "Bombed",
                ("bomb", False): "Bomb Off",
            }.get((feedback_kind, self._enabled), "")

        self._animation_group.stop()
        self.reposition(anchor_rect)
        self._opacity_effect.setOpacity(0.0)
        self.set_progress(0.0)
        self.show()
        self.raise_()
        self._animation_group.start()

    def _plate_rect(self) -> QRectF:
        rect = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        return QRectF(rect.left() + 6, rect.top() + 10, rect.width() - 12, rect.height() - 20)

    def _draw_plate(self, painter: QPainter, rect: QRectF, border_color: QColor):
        painter.save()
        painter.setPen(QPen(QColor(border_color.red(), border_color.green(), border_color.blue(), 96), 1.2))
        painter.setBrush(QColor(16, 20, 28, 148))
        painter.drawRoundedRect(rect, 18, 18)
        painter.restore()

    def _draw_label(self, painter: QPainter, rect: QRectF, title: str, color: QColor):
        painter.save()
        painter.setPen(color)
        font = QFont(self.font())
        font.setPointSize(max(11, int(rect.height() * 0.10)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, title)
        painter.restore()

    def _draw_soft_glow(self, painter: QPainter, center: QPointF, radius: float, inner: QColor, outer_alpha: int):
        gradient = QRadialGradient(center, max(1.0, radius))
        inner_color = QColor(inner)
        outer_color = QColor(inner)
        outer_color.setAlpha(max(0, int(outer_alpha)))
        gradient.setColorAt(0.0, inner_color)
        gradient.setColorAt(1.0, outer_color)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)
        painter.restore()

    def _draw_heart_feedback(self, painter: QPainter, rect: QRectF, progress: float, enabled: bool):
        icon_rect = QRectF(
            rect.left() + (rect.width() * 0.29),
            rect.top() + 12,
            rect.width() * 0.42,
            rect.height() * 0.48,
        )
        center = icon_rect.center()
        pulse = math.sin(min(1.0, progress / 0.42) * math.pi)
        glow_radius = (icon_rect.width() * 0.58) + (12.0 * pulse)
        accent = QColor(255, 102, 132) if enabled else QColor(176, 184, 196, 220)
        glow = QColor(accent)
        glow.setAlpha(160 if enabled else 90)
        self._draw_soft_glow(painter, center, glow_radius, glow, 0)

        heart_path = _heart_path(icon_rect)
        fill = QColor(255, 110, 138, 245) if enabled else QColor(115, 122, 134, 210)
        stroke = QColor(255, 222, 228, 230) if enabled else QColor(206, 212, 220, 170)
        painter.save()
        painter.setPen(QPen(stroke, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(fill)
        painter.drawPath(heart_path)
        painter.restore()

        self._draw_label(
            painter,
            rect.adjusted(0, 0, 0, -14),
            self._title,
            QColor(255, 240, 244, 230) if enabled else QColor(220, 225, 232, 210),
        )

    def _draw_bomb_feedback(self, painter: QPainter, rect: QRectF, progress: float, enabled: bool):
        icon_rect = QRectF(
            rect.left() + (rect.width() * 0.31),
            rect.top() + 34,
            rect.width() * 0.38,
            rect.height() * 0.42,
        )
        center = icon_rect.center()
        accent = QColor(255, 178, 92) if enabled else QColor(172, 178, 188, 205)
        outer_burst = QColor(255, 136, 52, 150) if enabled else QColor(114, 120, 130, 80)

        burst_progress = min(1.0, progress / 0.55)
        burst_outer = (icon_rect.width() * 0.34) + (icon_rect.width() * 0.40 * burst_progress)
        burst_inner = burst_outer * 0.46
        burst = _burst_path(center, burst_inner, burst_outer, points=8, rotation_deg=(-90.0 + (burst_progress * 12.0)))

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(outer_burst)
        painter.drawPath(burst)
        painter.restore()

        ring_pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 2.0)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.save()
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ring_idx in range(2):
            ring_progress = max(0.0, min(1.0, (burst_progress * 1.18) - (ring_idx * 0.20)))
            if ring_progress <= 0.0:
                continue
            radius = (icon_rect.width() * (0.34 + (ring_idx * 0.14))) + (icon_rect.width() * 0.34 * ring_progress)
            alpha = max(0, int(120 * (1.0 - ring_progress)))
            ring_pen.setColor(QColor(accent.red(), accent.green(), accent.blue(), alpha))
            painter.setPen(ring_pen)
            painter.drawEllipse(center, radius, radius)
        painter.restore()

        spark_outer = icon_rect.width() * (0.10 + (0.08 * math.sin(min(1.0, progress / 0.35) * math.pi)))
        spark_center = QPointF(icon_rect.right() - 4, icon_rect.top() + 6)
        spark = _burst_path(spark_center, spark_outer * 0.38, spark_outer, points=5)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 234, 164, 225 if enabled else 120))
        painter.drawPath(spark)
        painter.restore()

        bomb_path = _bomb_path(icon_rect)
        painter.save()
        painter.setPen(QPen(QColor(255, 224, 186, 235) if enabled else QColor(214, 220, 226, 165), 2.1,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(42, 44, 52, 228) if enabled else QColor(84, 88, 96, 190))
        painter.drawPath(bomb_path)
        painter.restore()

        self._draw_label(
            painter,
            rect.adjusted(0, 0, 0, -14),
            self._title,
            QColor(255, 244, 224, 228) if enabled else QColor(220, 225, 232, 205),
        )

    def _draw_stars_feedback(self, painter: QPainter, rect: QRectF, progress: float, stars: float):
        title_color = QColor(255, 246, 212, 232) if stars > 0.0 else QColor(220, 225, 232, 208)
        center = QPointF(rect.center().x(), rect.top() + (rect.height() * 0.34))
        self._draw_soft_glow(
            painter,
            center,
            (rect.width() * 0.24) + (8.0 * math.sin(min(1.0, progress / 0.45) * math.pi)),
            QColor(255, 205, 92, 120 if stars > 0.0 else 70),
            0,
        )

        star_count = 5
        star_area = QRectF(
            rect.left() + (rect.width() * 0.12),
            rect.top() + 18,
            rect.width() * 0.76,
            rect.height() * 0.34,
        )
        spacing = star_area.width() * 0.03
        star_size = min(
            star_area.height(),
            (star_area.width() - (spacing * (star_count - 1))) / float(star_count),
        )
        total_width = (star_size * star_count) + (spacing * (star_count - 1))
        left = star_area.left() + max(0.0, (star_area.width() - total_width) * 0.5)
        top = star_area.top() + max(0.0, (star_area.height() - star_size) * 0.5)
        intro = min(1.0, progress / 0.28)

        for index in range(star_count):
            x_pos = left + (index * (star_size + spacing))
            rect_star = QRectF(x_pos, top, star_size, star_size)
            transform = QTransform()
            transform.translate(rect_star.left(), rect_star.top())
            transform.scale(rect_star.width(), rect_star.height())
            path = transform.map(STAR_SHAPE)

            fill_fraction = max(0.0, min(1.0, stars - float(index)))
            painter.save()
            painter.setPen(QPen(QColor(219, 188, 96, 195) if stars > 0.0 else QColor(172, 178, 188, 135), 1.7))
            painter.setBrush(QColor(72, 76, 84, 110))
            painter.drawPath(path)

            fill_progress = max(0.0, min(1.0, (intro * 1.45) - (index * 0.10)))
            effective_fill = fill_fraction * fill_progress
            if effective_fill > 0.0:
                painter.save()
                painter.setClipRect(QRectF(rect_star.left(), rect_star.top(), rect_star.width() * effective_fill, rect_star.height()))
                painter.fillPath(path, QColor(255, 204, 72, 242))
                painter.restore()
            painter.restore()

        self._draw_label(painter, rect.adjusted(0, 0, 0, -14), self._title, title_color)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        progress = self.get_progress()
        plate_rect = self._plate_rect()
        lift = -12.0 * math.sin(min(1.0, progress) * (math.pi * 0.5))
        intro = min(1.0, progress / 0.24)
        bounce = math.sin(min(1.0, progress / 0.48) * math.pi)
        scale = 0.84 + (0.12 * intro) + (0.04 * bounce)
        if self._kind == "bomb":
            scale += 0.03 * math.sin(min(1.0, progress / 0.32) * math.pi)

        accent = {
            "love": QColor(255, 112, 140),
            "bomb": QColor(255, 170, 92),
            "stars": QColor(255, 206, 88),
        }.get(self._kind, QColor(220, 225, 232))

        painter.save()
        center = plate_rect.center()
        painter.translate(center.x(), center.y() + lift)
        painter.scale(scale, scale)
        painter.translate(-center.x(), -center.y())

        if self._kind == "stars":
            self._draw_plate(painter, plate_rect, accent)
        if self._kind == "love":
            self._draw_heart_feedback(painter, plate_rect, progress, self._enabled)
        elif self._kind == "bomb":
            self._draw_bomb_feedback(painter, plate_rect, progress, self._enabled)
        else:
            self._draw_stars_feedback(painter, plate_rect, progress, self._stars)
        painter.restore()
