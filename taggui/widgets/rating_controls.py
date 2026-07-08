import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QApplication, QAbstractButton, QSizePolicy, QWidget


def _star_path() -> QPainterPath:
    path = QPainterPath()
    points = []
    outer_radius = 0.48
    inner_radius = 0.21
    center_x = 0.5
    center_y = 0.5
    for point_index in range(10):
        angle_deg = -90.0 + (point_index * 36.0)
        radius = outer_radius if point_index % 2 == 0 else inner_radius
        angle_rad = math.radians(angle_deg)
        points.append(
            QPointF(
                center_x + (radius * math.cos(angle_rad)),
                center_y + (radius * math.sin(angle_rad)),
            )
        )
    if points:
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
    return path


STAR_SHAPE = _star_path()


class StarRatingWidget(QWidget):
    """Painted star rating control with half-star click and drag support."""

    rating_selected = Signal(float, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rating = 0.0
        self._mixed_state = False
        self._hover_rating = None
        self._pressed = False
        self._press_pos = None
        self._press_value = 0.0
        self._drag_last_value = None
        self._star_count = 5
        self._star_spacing = 4.0
        self._margin = 2.0
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            'Click or drag for half-star ratings.\n'
            'Ctrl+click filters exact stars.\n'
            'Ctrl+Shift+click filters minimum stars.\n'
            'Ctrl+0..5 sets rating.'
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(148, 28)

    def minimumSizeHint(self) -> QSize:
        return QSize(132, 24)

    def set_rating(self, value: float):
        clamped = max(0.0, min(float(self._star_count), float(value or 0.0)))
        if abs(clamped - self._rating) <= 1e-6:
            if not self._mixed_state:
                return
        self._rating = clamped
        self.update()

    def rating(self) -> float:
        return float(self._rating)

    def set_mixed_state(self, mixed: bool):
        mixed = bool(mixed)
        if mixed == self._mixed_state:
            return
        self._mixed_state = mixed
        self.update()

    def mixed_state(self) -> bool:
        return bool(self._mixed_state)

    def _star_rects(self) -> list[QRectF]:
        content_rect = QRectF(self.rect()).adjusted(
            self._margin,
            self._margin,
            -self._margin,
            -self._margin,
        )
        if content_rect.width() <= 0 or content_rect.height() <= 0:
            return []
        star_size = min(
            content_rect.height(),
            (content_rect.width() - (self._star_spacing * (self._star_count - 1))) / float(self._star_count),
        )
        if star_size <= 0:
            return []
        total_width = (star_size * self._star_count) + (self._star_spacing * (self._star_count - 1))
        left = content_rect.left() + max(0.0, (content_rect.width() - total_width) * 0.5)
        top = content_rect.top() + max(0.0, (content_rect.height() - star_size) * 0.5)
        return [
            QRectF(left + (index * (star_size + self._star_spacing)), top, star_size, star_size)
            for index in range(self._star_count)
        ]

    def _value_from_pos(self, pos) -> float:
        rects = self._star_rects()
        if not rects:
            return 0.0
        x_pos = float(pos.x())
        if x_pos <= rects[0].left():
            return 0.5
        if x_pos >= rects[-1].right():
            return float(self._star_count)
        for index, rect in enumerate(rects):
            if x_pos <= rect.right():
                midpoint = rect.left() + (rect.width() * 0.5)
                return min(
                    float(self._star_count),
                    float(index) + (0.5 if x_pos < midpoint else 1.0),
                )
        return float(self._star_count)

    def _effective_display_rating(self) -> float:
        if self._hover_rating is not None:
            return float(self._hover_rating)
        return float(self._rating)

    def _emit_rating(self, value: float, event: QMouseEvent):
        clamped = max(0.0, min(float(self._star_count), float(value or 0.0)))
        self.rating_selected.emit(clamped, event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._pressed = True
        self._press_pos = event.position().toPoint()
        self._press_value = self._value_from_pos(event.position())
        self._drag_last_value = None
        self._hover_rating = self._press_value
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        hover_value = self._value_from_pos(event.position())
        self._hover_rating = hover_value
        if self._pressed:
            drag_distance = (event.position().toPoint() - self._press_pos).manhattanLength()
            if drag_distance >= QApplication.startDragDistance():
                self._drag_last_value = hover_value
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            super().mouseReleaseEvent(event)
            return
        release_value = self._value_from_pos(event.position())
        drag_distance = (event.position().toPoint() - self._press_pos).manhattanLength()
        modifiers = event.modifiers()
        if drag_distance < QApplication.startDragDistance():
            if ((modifiers & Qt.KeyboardModifier.ControlModifier) != Qt.KeyboardModifier.ControlModifier
                    and abs(release_value - self._rating) <= 1e-6):
                release_value = 0.0
            self._emit_rating(release_value, event)
        elif self._drag_last_value is None or abs(self._drag_last_value - release_value) > 1e-6:
            self._emit_rating(release_value, event)
        self._pressed = False
        self._press_pos = None
        self._drag_last_value = None
        self._hover_rating = release_value if self.rect().contains(event.position().toPoint()) else None
        self.update()
        event.accept()

    def leaveEvent(self, event):
        if not self._pressed:
            self._hover_rating = None
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        palette = self.palette()
        active_fill = QColor(255, 196, 61)
        inactive_fill = palette.color(self.backgroundRole()).lighter(120)
        inactive_fill.setAlpha(90)
        outline = QColor(196, 145, 16)
        outline.setAlpha(220)
        mixed_accent = QColor(246, 153, 63)
        disabled_outline = palette.color(self.foregroundRole())
        disabled_outline.setAlpha(120)
        display_rating = 0.0 if self._mixed_state else self._effective_display_rating()

        if self._mixed_state:
            panel_rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            panel_fill = QColor(mixed_accent)
            panel_fill.setAlpha(28)
            painter.setPen(QPen(mixed_accent, 1.2))
            painter.setBrush(panel_fill)
            painter.drawRoundedRect(panel_rect, 7, 7)

        for index, rect in enumerate(self._star_rects()):
            transform = QTransform()
            transform.translate(rect.left(), rect.top())
            transform.scale(rect.width(), rect.height())
            star_path = transform.map(STAR_SHAPE)
            fill_fraction = max(0.0, min(1.0, display_rating - float(index)))

            painter.fillPath(star_path, inactive_fill)
            if fill_fraction > 0.0:
                painter.save()
                clip_rect = QRectF(rect.left(), rect.top(), rect.width() * fill_fraction, rect.height())
                painter.setClipRect(clip_rect)
                painter.fillPath(star_path, active_fill)
                painter.restore()

            pen = QPen(outline if self.isEnabled() else disabled_outline)
            pen.setWidthF(max(1.0, rect.width() * 0.08))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(star_path)

        if self._mixed_state:
            badge_radius = 5.0
            badge_center = QPointF(float(self.width()) - 10.0, 10.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mixed_accent)
            painter.drawEllipse(badge_center, badge_radius, badge_radius)
            painter.setPen(QPen(QColor(40, 28, 12), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(badge_center.x() - 2.2, badge_center.y()),
                QPointF(badge_center.x() + 2.2, badge_center.y()),
            )


class ReactionToggleButton(QAbstractButton):
    """Painted toggle button for simple binary media reactions."""

    filter_requested = Signal(str)

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = str(kind or '').strip().lower()
        self._filter_click_active = False
        self._mixed_state = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(30, 30)
        self._update_tooltip()

    def sizeHint(self) -> QSize:
        return QSize(30, 30)

    def _update_tooltip(self):
        if self._kind == 'love':
            self.setToolTip('Love this item (L)\nCtrl+click filters loved items')
        else:
            self.setToolTip('Bomb this item (B)\nCtrl+click filters bombed items')

    def set_mixed_state(self, mixed: bool):
        mixed = bool(mixed)
        if mixed == self._mixed_state:
            return
        self._mixed_state = mixed
        self.update()

    def mixed_state(self) -> bool:
        return bool(self._mixed_state)

    def _icon_path(self, rect: QRectF) -> QPainterPath:
        if self._kind == 'love':
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

    def mousePressEvent(self, event: QMouseEvent):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and (event.modifiers() & Qt.KeyboardModifier.ControlModifier) == Qt.KeyboardModifier.ControlModifier
        ):
            self._filter_click_active = True
            self.setDown(True)
            self.update()
            event.accept()
            return
        self._filter_click_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._filter_click_active:
            is_inside = self.rect().contains(event.position().toPoint())
            if self.isDown() != is_inside:
                self.setDown(is_inside)
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._filter_click_active:
            self._filter_click_active = False
            was_inside = self.rect().contains(event.position().toPoint())
            self.setDown(False)
            self.update()
            if was_inside:
                self.filter_requested.emit(self._kind)
            event.accept()
            return
        self._filter_click_active = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        base_rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        palette = self.palette()
        background = palette.color(self.backgroundRole()).lighter(112)
        background.setAlpha(180)
        border = palette.color(self.foregroundRole())
        border.setAlpha(110)
        icon_color = palette.color(self.foregroundRole())
        if self._kind == 'love':
            accent = QColor(230, 74, 90)
            checked_background = accent.lighter(155)
            checked_background.setAlpha(255)
            checked_border = accent.darker(135)
            checked_icon = accent.darker(165)
        else:
            accent = QColor(255, 140, 54)
            checked_background = QColor(36, 36, 40)
            checked_border = QColor(10, 10, 12)
            checked_icon = QColor(255, 181, 97)
        mixed_accent = QColor(246, 153, 63)
        if self._mixed_state:
            background = QColor(mixed_accent)
            background.setAlpha(34)
            border = QColor(mixed_accent)
            icon_color = QColor(214, 108, 26)
        elif self.isChecked():
            background = checked_background
            border = checked_border
            icon_color = checked_icon
        elif self.underMouse():
            background = background.lighter(118)

        painter.setPen(QPen(border, 1.4))
        painter.setBrush(background)
        painter.drawRoundedRect(base_rect, 7, 7)

        icon_rect = base_rect.adjusted(6, 6, -6, -6)
        painter.setPen(QPen(icon_color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(icon_color)
        painter.drawPath(self._icon_path(icon_rect))

        if self._mixed_state:
            badge_center = QPointF(base_rect.right() - 4.5, base_rect.top() + 4.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mixed_accent)
            painter.drawEllipse(badge_center, 3.5, 3.5)
            painter.setPen(QPen(QColor(40, 28, 12), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(badge_center.x() - 1.4, badge_center.y()),
                QPointF(badge_center.x() + 1.4, badge_center.y()),
            )
