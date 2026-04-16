"""Frameless floating host window for spawned image viewers."""

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QEvent, Qt, Signal, QTimer, QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QHelpEvent
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsView, QMenu,
                               QPushButton, QSizeGrip, QVBoxLayout, QWidget, QGraphicsOpacityEffect, QToolTip)

from utils.review_marks import (
    ReviewFlag,
    get_review_badge_corner_radius,
    get_review_badge_font_size,
    get_review_badge_specs,
    get_review_badge_text_color,
)


class FloatingReviewSlotsOverlay(QWidget):
    """Hover-only review-slot grid for masonry-wall floating viewers."""

    rank_requested = Signal(int)
    flag_requested = Signal(str)

    def __init__(self, viewer: QWidget, parent=None):
        super().__init__(parent)
        self._viewer = viewer
        self._enabled = False
        self._hover_active = False
        self._hovered_slot_key = None
        self._slot_size = 23
        self._slot_gap = 6
        self._panel_padding = 8

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self.setMouseTracking(True)
        self.hide()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b'opacity', self)
        self._fade_animation.setDuration(140)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_animation.finished.connect(self._on_fade_finished)

    def sizeHint(self) -> QSize:
        cols = 3
        rows = 3
        panel_w = (cols * self._slot_size) + ((cols - 1) * self._slot_gap) + (2 * self._panel_padding)
        panel_h = (rows * self._slot_size) + ((rows - 1) * self._slot_gap) + (2 * self._panel_padding)
        return QSize(panel_w, panel_h)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._fade_animation.stop()
            self._opacity_effect.setOpacity(0.0)
            self._hovered_slot_key = None
            self.hide()
        self.update()

    def set_hover_active(self, active: bool):
        self._hover_active = bool(active)
        should_show = bool(self._enabled and (self._hover_active or self._has_active_badges()))
        try:
            host = self.parentWidget()
            if host is not None and hasattr(host, "_reposition_overlay_controls"):
                host._reposition_overlay_controls()
        except Exception:
            pass
        self._fade_animation.stop()
        if should_show:
            self.show()
            self.raise_()
            start_opacity = float(self._opacity_effect.opacity())
            self._fade_animation.setStartValue(start_opacity)
            self._fade_animation.setEndValue(1.0 if self._hover_active else 0.96)
            self._fade_animation.start()
            self.update()
            return

        if not self.isVisible():
            return
        start_opacity = float(self._opacity_effect.opacity())
        if start_opacity <= 0.01:
            self._opacity_effect.setOpacity(0.0)
            self.hide()
            return
        self._fade_animation.setStartValue(start_opacity)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def refresh_state(self):
        try:
            host = self.parentWidget()
            if host is not None and hasattr(host, "_reposition_overlay_controls"):
                host._reposition_overlay_controls()
        except Exception:
            pass
        self.set_hover_active(self._hover_active)
        self.update()

    def _on_fade_finished(self):
        if float(self._opacity_effect.opacity()) <= 0.01:
            self.hide()
            self._hovered_slot_key = None

    def _current_review_state(self) -> tuple[int, int]:
        try:
            index = getattr(self._viewer, 'proxy_image_index', None)
            if index is None or not index.isValid():
                return 0, 0
            image = index.data(Qt.ItemDataRole.UserRole)
            if image is None:
                return 0, 0
            review_rank = int(getattr(image, 'review_rank', 0) or 0)
            review_flags = int(getattr(image, 'review_flags', 0) or 0)
            return review_rank, review_flags
        except Exception:
            return 0, 0

    def _slot_rect(self, item_index: int) -> QRect:
        cols = 3
        row = item_index // cols
        col = item_index % cols
        x = self._panel_padding + (col * (self._slot_size + self._slot_gap))
        y = self._panel_padding + (row * (self._slot_size + self._slot_gap))
        return QRect(x, y, self._slot_size, self._slot_size)

    def _hit_test_slot(self, pos: QPoint):
        for item_index, item in self._display_items():
            if self._slot_rect(item_index).contains(pos):
                return item
        return None

    def _slot_items(self):
        return get_review_badge_specs()

    def _active_badge_items(self, review_rank: int, review_flags: int):
        return [
            item for item in self._slot_items()
            if self._slot_is_active(item, review_rank, review_flags)
        ]

    def _has_active_badges(self) -> bool:
        review_rank, review_flags = self._current_review_state()
        return bool(review_rank or review_flags)

    def _display_items(self):
        review_rank, review_flags = self._current_review_state()
        if self._hover_active:
            return list(enumerate(self._slot_items()))
        return [
            (item_index, item)
            for item_index, item in enumerate(self._slot_items())
            if self._slot_is_active(item, review_rank, review_flags)
        ]

    def _slot_is_active(self, spec, review_rank: int, review_flags: int) -> bool:
        if spec.kind == 'rank':
            return int(review_rank) == int(spec.rank or 0) and (int(review_flags) & int(ReviewFlag.REJECT)) == 0
        if spec.kind == 'flag':
            return bool(int(review_flags) & int(spec.flag))
        return False

    def mouseMoveEvent(self, event):
        hit = self._hit_test_slot(event.position().toPoint())
        slot_key = str(getattr(hit, 'badge_id', '') or '') if hit is not None else None
        if slot_key != self._hovered_slot_key:
            self._hovered_slot_key = slot_key
            self.update()
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if hit is not None else
            Qt.CursorShape.ArrowCursor
        )
        event.accept()
        super().mouseMoveEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            help_event = event if isinstance(event, QHelpEvent) else None
            pos = help_event.pos() if help_event is not None else QPoint()
            hit = self._hit_test_slot(pos)
            if hit is None:
                QToolTip.hideText()
                event.ignore()
                return True
            QToolTip.showText(help_event.globalPos(), str(hit.title or "Add badge to image"), self)
            return True
        return super().event(event)

    def leaveEvent(self, event):
        self._hovered_slot_key = None
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        hit = self._hit_test_slot(event.position().toPoint())
        if hit is not None:
            if hit.kind == 'rank':
                self.rank_requested.emit(int(hit.rank or 0))
            else:
                self.flag_requested.emit(str(hit.flag_name or ''))
        self.update()
        event.accept()

    def paintEvent(self, event):
        if not self._enabled:
            return

        review_rank, review_flags = self._current_review_state()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if self._hover_active:
            panel_rect = self.rect().adjusted(1, 1, -1, -1)
            painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
            painter.setBrush(QColor(10, 14, 22, 116))
            painter.drawRoundedRect(panel_rect, 14, 14)

        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(float(get_review_badge_font_size()))
        painter.setFont(font)
        radius = float(get_review_badge_corner_radius())
        inner_radius = max(2.0, radius - 2.0)
        glow_radius = min(14.0, radius + 2.0)
        text_base_color = QColor(get_review_badge_text_color())

        display_items = self._display_items()
        if not display_items:
            return

        for item_index, item in display_items:
            slot_rect = self._slot_rect(item_index)
            is_active = self._slot_is_active(item, review_rank, review_flags)
            is_hovered = self._hovered_slot_key == str(item.badge_id)
            base_color = QColor(item.color)

            shadow_rect = slot_rect.translated(0, 1)
            shadow_alpha = 82 if (is_active or is_hovered) else 42
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, shadow_alpha))
            painter.drawRoundedRect(shadow_rect, radius, radius)

            outline_color = QColor(base_color)
            outline_color.setAlpha(240 if is_active else (210 if is_hovered else 150))
            fill_color = QColor(base_color)
            fill_color.setAlpha(232 if is_active else (58 if is_hovered else 24))

            if is_hovered and not is_active:
                glow_color = QColor(base_color)
                glow_color.setAlpha(48)
                painter.setBrush(glow_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(slot_rect.adjusted(-2, -2, 2, 2), glow_radius, glow_radius)

            painter.setBrush(fill_color)
            painter.setPen(QPen(outline_color, 1.3))
            painter.drawRoundedRect(slot_rect, radius, radius)

            inner_rect = slot_rect.adjusted(3, 3, -3, -3)
            if not is_active:
                inner_outline = QColor(base_color)
                inner_outline.setAlpha(125 if is_hovered else 86)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(inner_outline, 1.0))
                painter.drawRoundedRect(inner_rect, inner_radius, inner_radius)

            text_color = QColor(text_base_color)
            text_color.setAlpha(248 if is_active else (232 if is_hovered else 188))
            painter.setPen(text_color)
            painter.drawText(slot_rect, Qt.AlignmentFlag.AlignCenter, str(item.label))


class ShiftResizeCornerCue(QWidget):
    """Painted L-corner cue with a moving highlight runner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._corner = None
        self._runner_progress = 0.0
        self._pulse = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def set_corner_state(self, corner: str | None, runner_progress: float, pulse: float):
        if corner not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            self._corner = None
            self.hide()
            return
        self._corner = str(corner)
        self._runner_progress = max(0.0, min(1.0, float(runner_progress)))
        self._pulse = max(0.0, min(1.0, float(pulse)))
        self.show()
        self.update()

    @staticmethod
    def _draw_polyline_segment(painter: QPainter, pen: QPen, points: list[QPointF], start_pos: float, span: float):
        if len(points) < 2 or span <= 0:
            return
        painter.save()
        painter.setPen(pen)
        cursor = max(0.0, float(start_pos))
        remaining = float(span)
        for index in range(len(points) - 1):
            start_point = points[index]
            end_point = points[index + 1]
            seg_dx = float(end_point.x()) - float(start_point.x())
            seg_dy = float(end_point.y()) - float(start_point.y())
            seg_len = math.hypot(seg_dx, seg_dy)
            if seg_len <= 1e-6:
                continue
            if cursor >= seg_len:
                cursor -= seg_len
                continue
            local_start = cursor
            local_end = min(seg_len, local_start + remaining)
            t0 = local_start / seg_len
            t1 = local_end / seg_len
            seg_start = QPointF(
                float(start_point.x()) + (seg_dx * t0),
                float(start_point.y()) + (seg_dy * t0),
            )
            seg_end = QPointF(
                float(start_point.x()) + (seg_dx * t1),
                float(start_point.y()) + (seg_dy * t1),
            )
            painter.drawLine(seg_start, seg_end)
            remaining -= (local_end - local_start)
            if remaining <= 1e-6:
                break
            cursor = 0.0
        painter.restore()

    @classmethod
    def _draw_wrapped_polyline_segment(
        cls,
        painter: QPainter,
        pen: QPen,
        points: list[QPointF],
        start_pos: float,
        span: float,
        total_length: float,
    ):
        if total_length <= 1e-6 or span <= 0:
            return
        wrapped_start = float(start_pos) % total_length
        first_span = min(span, total_length - wrapped_start)
        cls._draw_polyline_segment(painter, pen, points, wrapped_start, first_span)
        remaining = span - first_span
        if remaining > 1e-6:
            cls._draw_polyline_segment(painter, pen, points, 0.0, remaining)

    def paintEvent(self, event):
        if self._corner is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = float(self.width())
        height = float(self.height())
        inset = 3.0
        arm = max(8.0, min(width, height) - (2.0 * inset))
        if self._corner == "top_left":
            corner = QPointF(inset, inset)
            horizontal_end = QPointF(inset + arm, inset)
            vertical_end = QPointF(inset, inset + arm)
        elif self._corner == "top_right":
            corner = QPointF(width - inset, inset)
            horizontal_end = QPointF(width - inset - arm, inset)
            vertical_end = QPointF(width - inset, inset + arm)
        elif self._corner == "bottom_left":
            corner = QPointF(inset, height - inset)
            horizontal_end = QPointF(inset + arm, height - inset)
            vertical_end = QPointF(inset, height - inset - arm)
        else:
            corner = QPointF(width - inset, height - inset)
            horizontal_end = QPointF(width - inset - arm, height - inset)
            vertical_end = QPointF(width - inset, height - inset - arm)

        points = [horizontal_end, corner, vertical_end]
        total_length = max(1e-6, 2.0 * arm)
        runner_head = float(self._runner_progress) * total_length
        runner_span = max(12.0, arm * 0.30)
        trail_step = max(6.0, runner_span * 0.32)

        glow_pen = QPen(QColor(84, 255, 148, 42))
        glow_pen.setWidthF(7.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        base_pen = QPen(QColor(154, 255, 190, 132))
        base_pen.setWidthF(2.6)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        base_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(glow_pen)
        painter.drawLine(corner, horizontal_end)
        painter.drawLine(corner, vertical_end)
        painter.setPen(base_pen)
        painter.drawLine(corner, horizontal_end)
        painter.drawLine(corner, vertical_end)

        trail_specs = (
            (0.0, runner_span, QColor(212, 255, 222, int(round(118 + (36 * self._pulse)))), 8.0),
            (trail_step, runner_span * 0.78, QColor(144, 255, 178, int(round(84 + (28 * self._pulse)))), 5.6),
            (trail_step * 1.9, runner_span * 0.54, QColor(88, 245, 146, int(round(52 + (20 * self._pulse)))), 3.8),
        )
        for offset, span, color, width_value in trail_specs:
            runner_pen = QPen(color)
            runner_pen.setWidthF(width_value)
            runner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            runner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self._draw_wrapped_polyline_segment(
                painter,
                runner_pen,
                points,
                runner_head - offset,
                span,
                total_length,
            )

        head_glow_pen = QPen(QColor(255, 255, 255, 238))
        head_glow_pen.setWidthF(3.2)
        head_glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        head_glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._draw_wrapped_polyline_segment(
            painter,
            head_glow_pen,
            points,
            runner_head - (runner_span * 0.24),
            max(7.0, runner_span * 0.34),
            total_length,
        )


class FloatingViewerWindow(QWidget):
    """Minimal floating window that hosts one ImageViewer instance."""

    activated = Signal(object)  # Emits hosted viewer
    closing = Signal(object)    # Emits hosted viewer
    sync_video_requested = Signal()
    close_all_requested = Signal()
    compare_drag_started = Signal(object, QPoint)
    compare_drag_moved = Signal(object, QPoint)
    compare_drag_released = Signal(object, QPoint)
    compare_drag_canceled = Signal(object)
    compare_exit_requested = Signal(object)
    review_rank_requested = Signal(int)
    review_flag_requested = Signal(str)

    def __init__(self, viewer: QWidget, title: str, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint,
        )
        self.viewer = viewer
        self._window_drag_active = False
        self._window_drag_button = Qt.MouseButton.NoButton
        self._window_drag_offset = QPoint()
        self._active_drag_handle = None
        self._compare_drag_signal_active = False
        self._close_button_margin_px = 8
        self._close_button_clearance_px = 4
        self._active = False
        self._close_hover_zone_px = 56
        self._drag_hover_padding_px = 10
        self._drag_handle_widgets: dict[str, QWidget] = {}
        self._drag_line_widgets: dict[str, QWidget] = {}
        self._drag_widget_to_handle: dict[QWidget, str] = {}
        self._corner_resize_widgets: dict[str, QWidget] = {}
        self._corner_widget_to_corner: dict[QWidget, str] = {}
        self._edge_resize_widgets: dict[str, QWidget] = {}
        self._edge_widget_to_edge: dict[QWidget, str] = {}
        self._resize_active = False
        self._resize_corner = None
        self._resize_start_geometry = QRect()
        self._resize_start_global_pos = QPoint()
        self._resize_prev_anchor = None
        self._resize_start_zoom_factor = 1.0
        self._resize_start_zoom_to_fit = True
        self._resize_start_focus_scene_pos = QPointF()
        self._shift_resize_visual_zone = None
        self._shift_resize_glow_phase = 0.0
        self._video_controls_widget = None
        self._frozen_passthrough_mode = False
        self._frozen_tint_overlay = QWidget(self)
        self._frozen_tint_overlay.setObjectName("floatingViewerFrozenTint")
        self._frozen_tint_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._frozen_tint_overlay.hide()
        self._frozen_outline = QWidget(self)
        self._frozen_outline.setObjectName("floatingViewerFrozenOutline")
        self._frozen_outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._frozen_outline.hide()
        self._frozen_tint_overlay.raise_()
        self._frozen_outline.raise_()
        self._shift_resize_corner_cue = ShiftResizeCornerCue(self)
        self._shift_resize_corner_cue.hide()
        self._shift_resize_corner_cue.raise_()
        self._review_slots_enabled = False
        self._review_slots_overlay = FloatingReviewSlotsOverlay(self.viewer, self)
        self._review_slots_overlay.rank_requested.connect(self._handle_review_rank_requested)
        self._review_slots_overlay.flag_requested.connect(self._handle_review_flag_requested)
        self._review_slots_overlay.hide()
        self._review_slots_overlay.raise_()
        self._shift_resize_glow_timer = QTimer(self)
        self._shift_resize_glow_timer.setInterval(40)
        self._shift_resize_glow_timer.timeout.connect(self._tick_shift_resize_glow)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("floatingViewerWindow")
        self.setWindowTitle(title)
        self.setMinimumSize(24, 24)
        self.setMouseTracking(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.viewer)

        if hasattr(self.viewer, "view"):
            self.viewer.view.setFrameShape(QFrame.Shape.NoFrame)
            self.viewer.view.setLineWidth(0)
            self.viewer.view.setMidLineWidth(0)

        self._close_button = QPushButton("X", self)
        self._close_button.setObjectName("floatingViewerClose")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setToolTip("Close floating viewer")
        self._close_button.clicked.connect(self.close)
        self._close_button.hide()
        self._close_button.raise_()

        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(14, 14)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")
        # Resize is handled by border hit-testing; keep grip hidden to avoid
        # visible corner artifacts over native video surfaces.
        self._size_grip.hide()
        self._size_grip.raise_()

        self._create_drag_handles()
        self._create_corner_resize_handles()
        self._create_edge_resize_handles()
        self._use_widget_resize_handles = False
        self._disable_widget_resize_handles()

        self.viewer.installEventFilter(self)
        self.installEventFilter(self)
        self._video_controls_widget = getattr(self.viewer, "video_controls", None)
        self._install_hosted_viewer_event_filters()
        if hasattr(self.viewer, "activated"):
            self.viewer.activated.connect(self._emit_activated)

        self._apply_style()
        self._reposition_overlay_controls()

    def _disable_widget_resize_handles(self):
        """Hide legacy resize widgets to avoid native-video corner artifacts."""
        for zone in self._corner_resize_widgets.values():
            try:
                zone.hide()
                zone.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            except Exception:
                pass
        for zone in self._edge_resize_widgets.values():
            try:
                zone.hide()
                zone.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

    def _shift_resize_modifiers_active(self) -> bool:
        try:
            return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        except Exception:
            return False

    def _tick_shift_resize_glow(self):
        if self._shift_resize_visual_zone is None:
            self._shift_resize_glow_timer.stop()
            return
        self._shift_resize_glow_phase = (float(self._shift_resize_glow_phase) + 0.24) % (2.0 * math.pi)
        self._apply_shift_resize_visuals()

    def _apply_shift_resize_visuals(self):
        zone_name = self._shift_resize_visual_zone
        pulse = 0.5 + (0.5 * math.sin(float(self._shift_resize_glow_phase)))
        clear_style = "background: transparent; border: none;"
        cue = self._shift_resize_corner_cue
        for name, zone in self._corner_resize_widgets.items():
            zone.setStyleSheet(clear_style)
            zone.hide()
        for name, zone in self._edge_resize_widgets.items():
            zone.setStyleSheet(clear_style)
            zone.hide()

        if zone_name not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            cue.set_corner_state(None, 0.0, 0.0)
            return

        cue_size = 34
        edge_margin = 1
        if zone_name == "top_left":
            cue_x = edge_margin
            cue_y = edge_margin
        elif zone_name == "top_right":
            cue_x = max(0, self.width() - cue_size - edge_margin)
            cue_y = edge_margin
        elif zone_name == "bottom_left":
            cue_x = edge_margin
            cue_y = max(0, self.height() - cue_size - edge_margin)
        else:
            cue_x = max(0, self.width() - cue_size - edge_margin)
            cue_y = max(0, self.height() - cue_size - edge_margin)

        cue.setGeometry(cue_x, cue_y, cue_size, cue_size)
        cue.set_corner_state(
            zone_name,
            runner_progress=(float(self._shift_resize_glow_phase) / (2.0 * math.pi)) % 1.0,
            pulse=pulse,
        )
        cue.raise_()

    def _update_shift_resize_visuals(self, global_pos: QPoint | None = None):
        zone_name = None
        if self._shift_resize_modifiers_active():
            if self._resize_active and self._resize_corner:
                zone_name = self._resize_corner
            else:
                probe_pos = global_pos if global_pos is not None else QCursor.pos()
                try:
                    local_pos = self.mapFromGlobal(probe_pos)
                except Exception:
                    local_pos = QPoint(-1, -1)
                zone_name = self._resize_zone_from_local_pos(local_pos)

        if zone_name != self._shift_resize_visual_zone:
            self._shift_resize_visual_zone = zone_name
            if zone_name is None:
                self._shift_resize_glow_timer.stop()
                self._shift_resize_glow_phase = 0.0
            elif not self._shift_resize_glow_timer.isActive():
                self._shift_resize_glow_timer.start()
            self._apply_shift_resize_visuals()
            return

        if zone_name is not None and not self._shift_resize_glow_timer.isActive():
            self._shift_resize_glow_timer.start()
        if zone_name is None:
            self._apply_shift_resize_visuals()

    def _event_global_pos(self, event) -> QPoint:
        try:
            if hasattr(event, "globalPosition"):
                return event.globalPosition().toPoint()
            if hasattr(event, "globalPos"):
                return event.globalPos()
        except Exception:
            pass
        return QCursor.pos()

    def _iter_video_surface_widgets(self):
        """Yield live native video surface widgets used by backend renderers."""
        player = getattr(self.viewer, "video_player", None)
        if player is None:
            return
        for attr in ("vlc_widget", "mpv_widget"):
            widget = getattr(player, attr, None)
            if isinstance(widget, QWidget):
                yield widget

    def _refresh_video_surface_event_filters(self):
        """Ensure floating-window event filter is attached to backend video widgets."""
        for widget in self._iter_video_surface_widgets():
            try:
                widget.installEventFilter(self)
                widget.setMouseTracking(True)
            except RuntimeError:
                # Surface may be recreated while switching videos/backends.
                continue

    def _install_hosted_viewer_event_filters(self):
        """Attach this window as the event filter for its hosted viewer tree."""
        try:
            if hasattr(self.viewer, "view"):
                self.viewer.view.installEventFilter(self)
                self.viewer.view.viewport().installEventFilter(self)
        except RuntimeError:
            pass
        self._refresh_video_surface_event_filters()
        if self._video_controls_widget is not None:
            try:
                self._video_controls_widget.installEventFilter(self)
            except RuntimeError:
                self._video_controls_widget = None

    def _remove_hosted_viewer_event_filters(self):
        """Detach this window from the hosted viewer tree before external reparenting."""
        try:
            self.viewer.removeEventFilter(self)
        except RuntimeError:
            pass
        try:
            if hasattr(self.viewer, "view"):
                self.viewer.view.removeEventFilter(self)
                self.viewer.view.viewport().removeEventFilter(self)
        except RuntimeError:
            pass
        for widget in self._iter_video_surface_widgets():
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                continue
        if self._video_controls_widget is not None:
            try:
                self._video_controls_widget.removeEventFilter(self)
            except RuntimeError:
                self._video_controls_widget = None

    def detach_hosted_viewer_for_external_reparent(self):
        """Hide this host and release the viewer for temporary fullscreen hosting."""
        self._remove_hosted_viewer_event_filters()
        layout = self.layout()
        if layout is not None:
            layout.removeWidget(self.viewer)
        self.viewer.setParent(None)
        self.hide()

    def attach_hosted_viewer_after_external_reparent(self):
        """Restore a viewer previously detached for temporary fullscreen hosting."""
        layout = self.layout()
        if layout is not None:
            layout.addWidget(self.viewer)
        self._video_controls_widget = getattr(self.viewer, "video_controls", None)
        self._install_hosted_viewer_event_filters()
        self.show()
        self.raise_()
        self.activateWindow()
        self._reposition_overlay_controls()

    def refresh_video_controls_performance_profile(self):
        """Proxy performance-profile refresh request to main window."""
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'refresh_video_controls_performance_profile'):
            try:
                parent.refresh_video_controls_performance_profile()
            except Exception:
                pass

    def _viewer_content_is_pannable(self) -> bool:
        checker = getattr(self.viewer, "is_content_pannable", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def _uses_handle_only_window_drag(self) -> bool:
        """When pannable, image drag is reserved for panning and handles move window."""
        return self._viewer_content_is_pannable()

    def _press_hits_marking(self, watched, event) -> bool:
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return False
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                scene_pos = view.mapToScene(pos)
            elif watched is view:
                scene_pos = view.mapToScene(pos)
            elif watched is self.viewer:
                mapped = self.viewer.mapTo(view.viewport(), pos)
                scene_pos = view.mapToScene(mapped)
            else:
                return False

            item = view.scene().itemAt(scene_pos, view.transform())
            if item is None:
                return False

            from widgets.marking import MarkingItem, MarkingLabel
            current = item
            while current is not None:
                if isinstance(current, (MarkingItem, MarkingLabel)):
                    return True
                current = current.parentItem()
        except Exception:
            return False
        return False

    def _event_scene_pos(self, watched, event):
        """Map mouse event position to viewer scene coordinates."""
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return view.mapToScene(pos)
            if watched is view:
                return view.mapToScene(pos)
            if watched is self.viewer:
                mapped = self.viewer.mapTo(view.viewport(), pos)
                return view.mapToScene(mapped)
            if isinstance(watched, QWidget):
                mapped = watched.mapTo(view.viewport(), pos)
                return view.mapToScene(mapped)
        except Exception:
            return None
        return None

    def _event_viewport_pos(self, watched, event):
        """Map mouse event position to viewer viewport coordinates."""
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return pos
            if watched is view:
                return view.viewport().mapFrom(view, pos)
            if watched is self.viewer:
                return self.viewer.mapTo(view.viewport(), pos)
            if isinstance(watched, QWidget):
                return watched.mapTo(view.viewport(), pos)
        except Exception:
            return None
        return None

    def _should_start_surface_window_drag(self, watched, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self._uses_handle_only_window_drag():
            return False

        # Keep marking interactions functional when annotations are present.
        if self._press_hits_marking(watched, event):
            return False

        try:
            view = getattr(self.viewer, "view", None)
            if view is not None and bool(getattr(view, "insertion_mode", False)):
                return False
        except Exception:
            pass

        local_pos = self.mapFromGlobal(self._event_global_pos(event))
        if self._close_button.geometry().contains(local_pos):
            return False
        return True

    def _begin_window_drag(self, event, handle_name: str | None):
        global_pos = self._event_global_pos(event)
        drag_button = Qt.MouseButton.LeftButton
        try:
            if hasattr(event, "button"):
                drag_button = event.button()
        except Exception:
            pass
        self._window_drag_active = True
        self._window_drag_button = drag_button
        self._active_drag_handle = handle_name
        self._window_drag_offset = global_pos - self.frameGeometry().topLeft()
        self._emit_activated()
        self._update_overlay_hover_from_global_pos(global_pos)
        if not self._compare_drag_signal_active:
            self._compare_drag_signal_active = True
            self.compare_drag_started.emit(self, global_pos)

    def _cancel_compare_drag_signal(self):
        if not self._compare_drag_signal_active:
            return
        self._compare_drag_signal_active = False
        self.compare_drag_canceled.emit(self)

    def _is_window_drag_button_down(self, event) -> bool:
        if not self._window_drag_active or self._window_drag_button == Qt.MouseButton.NoButton:
            return False
        try:
            return bool(event.buttons() & self._window_drag_button)
        except Exception:
            return False

    def _create_drag_handles(self):
        """Create draggable edge handles used to move the floating window."""
        for name in ("top", "right", "bottom", "left"):
            zone = QWidget(self)
            zone.setObjectName("floatingViewerDragZone")
            zone.setCursor(Qt.CursorShape.SizeAllCursor)
            zone.setToolTip("Drag floating viewer")
            zone.hide()
            zone.raise_()
            zone.installEventFilter(self)

            try:
                line = QWidget(zone)
            except Exception:
                # Some PySide builds can fail constructing a QWidget with parent in one call.
                line = QWidget()
                line.setParent(zone)
            line.setObjectName("floatingViewerDragLine")
            line.installEventFilter(self)

            self._drag_handle_widgets[name] = zone
            self._drag_line_widgets[name] = line
            self._drag_widget_to_handle[zone] = name
            self._drag_widget_to_handle[line] = name

    def _create_corner_resize_handles(self):
        """Create invisible corner handles used for resize from all corners."""
        cursor_by_corner = {
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        for corner, cursor in cursor_by_corner.items():
            zone = QWidget(self)
            zone.setObjectName("floatingViewerResizeCorner")
            zone.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            zone.setCursor(cursor)
            zone.setToolTip("Resize floating viewer")
            zone.setMouseTracking(True)
            zone.raise_()
            zone.installEventFilter(self)
            self._corner_resize_widgets[corner] = zone
            self._corner_widget_to_corner[zone] = corner

    def _create_edge_resize_handles(self):
        """Create invisible border handles used for resize from all sides."""
        cursor_by_edge = {
            "top": Qt.CursorShape.SizeVerCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
        }
        for edge, cursor in cursor_by_edge.items():
            zone = QWidget(self)
            zone.setObjectName("floatingViewerResizeEdge")
            zone.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            zone.setCursor(cursor)
            zone.setToolTip("Resize floating viewer")
            zone.setMouseTracking(True)
            zone.raise_()
            zone.installEventFilter(self)
            self._edge_resize_widgets[edge] = zone
            self._edge_widget_to_edge[zone] = edge

    def _emit_activated(self):
        self.activated.emit(self.viewer)

    def _handle_review_rank_requested(self, rank: int):
        self._emit_activated()
        self.review_rank_requested.emit(int(rank))
        self._review_slots_overlay.set_hover_active(True)
        self.refresh_review_slots_overlay()

    def _handle_review_flag_requested(self, flag_name: str):
        self._emit_activated()
        self.review_flag_requested.emit(str(flag_name))
        self._review_slots_overlay.set_hover_active(True)
        self.refresh_review_slots_overlay()

    def set_review_slots_enabled(self, enabled: bool):
        self._review_slots_enabled = bool(enabled)
        self._review_slots_overlay.set_enabled(self._review_slots_enabled)
        self._reposition_overlay_controls()
        if not self._review_slots_enabled:
            self._review_slots_overlay.set_hover_active(False)

    def refresh_review_slots_overlay(self):
        if self._review_slots_overlay is not None:
            self._review_slots_overlay.refresh_state()

    def _set_widget_tree_mouse_passthrough(self, enabled: bool):
        widgets = [self]
        widgets.extend(self.findChildren(QWidget))
        for widget in widgets:
            try:
                widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(enabled))
            except Exception:
                pass

        # Keep passive overlays passive regardless of mode.
        for overlay in (self._frozen_tint_overlay, self._frozen_outline, self._shift_resize_corner_cue):
            try:
                overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

    def _set_native_mouse_passthrough(self, enabled: bool) -> bool:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", None) or getattr(user32, "GetWindowLongW", None)
            set_style = getattr(user32, "SetWindowLongPtrW", None) or getattr(user32, "SetWindowLongW", None)
            if get_style is None or set_style is None:
                return False

            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            current_style = int(get_style(hwnd, GWL_EXSTYLE))
            target_style = (
                current_style | WS_EX_TRANSPARENT
                if enabled else
                current_style & ~WS_EX_TRANSPARENT
            )
            if target_style == current_style:
                return True

            set_style(hwnd, GWL_EXSTYLE, target_style)
            SWP_NOMOVE = 0x0001
            SWP_NOSIZE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            return True
        except Exception:
            return False

    def _refresh_viewer_after_window_transition(self):
        refresher = getattr(self.viewer, "refresh_after_host_window_transition", None)
        if callable(refresher):
            try:
                refresher()
                return
            except Exception:
                pass
        try:
            view = getattr(self.viewer, "view", None)
            if view is not None and hasattr(view, "viewport"):
                view.viewport().update()
        except Exception:
            pass

    def _force_activate_viewer_owner(self):
        """Force main-window active viewer switch for strict single-controls mode."""
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'set_active_viewer'):
            try:
                parent.set_active_viewer(self.viewer)
                return
            except Exception:
                pass
        self._emit_activated()

    def set_frozen_passthrough_mode(self, enabled: bool):
        """Gray out and make this floating window input-transparent."""
        enabled = bool(enabled)
        if self._frozen_passthrough_mode == enabled:
            return
        self._frozen_passthrough_mode = enabled

        opacity = 0.46 if enabled else 1.0
        self.setWindowOpacity(opacity)
        used_native_passthrough = self._set_native_mouse_passthrough(enabled)
        self._set_widget_tree_mouse_passthrough(False if used_native_passthrough else enabled)

        if enabled:
            self._show_close_button(False)
            self._hide_all_drag_handles()
            self._frozen_tint_overlay.show()
            self._frozen_tint_overlay.raise_()
            self._frozen_outline.show()
            self._frozen_outline.raise_()
        else:
            self._frozen_tint_overlay.hide()
            self._frozen_outline.hide()
        self._apply_style()
        QTimer.singleShot(0, self._refresh_viewer_after_window_transition)

    def set_active(self, active: bool):
        self._active = bool(active)
        self._apply_style()

    def _apply_style(self):
        border_alpha = "180" if self._active else "130"
        self.setStyleSheet(
            f"""
            #floatingViewerClose {{
                border: 1px solid rgba(255, 255, 255, 110);
                border-radius: 5px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(44, 51, 61, {border_alpha}),
                    stop: 1 rgba(22, 28, 36, {border_alpha})
                );
                color: rgba(248, 250, 252, 245);
                font-size: 13px;
                font-weight: 800;
                padding: 0px;
                text-align: center;
            }}
            #floatingViewerClose:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(255, 110, 110, 245),
                    stop: 1 rgba(214, 42, 42, 245)
                );
                border: 1px solid rgba(255, 190, 190, 235);
                color: rgba(255, 255, 255, 255);
            }}
            #floatingViewerClose:pressed {{
                background: rgba(168, 24, 24, 245);
                border: 1px solid rgba(255, 170, 170, 220);
                color: rgba(255, 245, 245, 255);
            }}
            #floatingViewerDragZone {{
                background: transparent;
            }}
            #floatingViewerDragLine {{
                border: 1px solid rgba(0, 0, 0, 140);
                border-radius: 2px;
                background: rgba(255, 255, 255, {border_alpha});
            }}
            #floatingViewerResizeCorner {{
                background: transparent;
                border: none;
            }}
            #floatingViewerResizeEdge {{
                background: transparent;
                border: none;
            }}
            #floatingViewerFrozenTint {{
                border: none;
                background: rgba(136, 142, 156, 104);
            }}
            #floatingViewerFrozenOutline {{
                border: 3px solid rgba(28, 112, 255, 255);
                background: transparent;
            }}
            """
        )

    def _reposition_overlay_controls(self):
        margin = self._close_button_margin_px
        self._frozen_tint_overlay.setGeometry(0, 0, self.width(), self.height())
        self._frozen_outline.setGeometry(0, 0, self.width(), self.height())
        corner_size = 18
        corner_gap = self._close_button_clearance_px
        # Keep close near top-right, but slightly inset from borders.
        close_x = max(
            0,
            self.width() - self._close_button.width() - margin - max(2, corner_size // 3),
        )
        close_y = max(0, min(self.height() - self._close_button.height(), margin + max(4, corner_size // 3)))
        # If still colliding with the top-right corner resizer, nudge down just enough.
        corner_block_rect = QRect(
            max(0, self.width() - corner_size - corner_gap),
            0,
            corner_size + corner_gap,
            corner_size + corner_gap,
        )
        close_rect = QRect(close_x, close_y, self._close_button.width(), self._close_button.height())
        if close_rect.intersects(corner_block_rect):
            close_y = min(
                max(0, self.height() - self._close_button.height()),
                corner_block_rect.bottom() + 1,
            )
        self._close_button.move(close_x, close_y)

        available_w = max(4, self.width() - (2 * margin))
        available_h = max(4, self.height() - (2 * margin))
        handle_len_h = min(max(24, int(self.width() * 0.15)), available_w)
        handle_len_v = min(max(24, int(self.height() * 0.15)), available_h)
        handle_thickness = min(18, max(6, min(self.width(), self.height()) - 2))
        line_thickness = 4

        top_x = (self.width() - handle_len_h) // 2
        top_y = margin - 1
        top_zone = self._drag_handle_widgets["top"]
        top_zone.setGeometry(top_x, top_y, handle_len_h, handle_thickness)
        self._drag_line_widgets["top"].setGeometry(
            0,
            (handle_thickness - line_thickness) // 2,
            handle_len_h,
            line_thickness,
        )

        bottom_x = top_x
        bottom_y = self.height() - margin - handle_thickness + 1
        bottom_zone = self._drag_handle_widgets["bottom"]
        bottom_zone.setGeometry(bottom_x, bottom_y, handle_len_h, handle_thickness)
        self._drag_line_widgets["bottom"].setGeometry(
            0,
            (handle_thickness - line_thickness) // 2,
            handle_len_h,
            line_thickness,
        )

        left_x = margin - 1
        left_y = (self.height() - handle_len_v) // 2
        left_zone = self._drag_handle_widgets["left"]
        left_zone.setGeometry(left_x, left_y, handle_thickness, handle_len_v)
        self._drag_line_widgets["left"].setGeometry(
            (handle_thickness - line_thickness) // 2,
            0,
            line_thickness,
            handle_len_v,
        )

        right_x = self.width() - margin - handle_thickness + 1
        right_y = left_y
        right_zone = self._drag_handle_widgets["right"]
        right_zone.setGeometry(right_x, right_y, handle_thickness, handle_len_v)
        self._drag_line_widgets["right"].setGeometry(
            (handle_thickness - line_thickness) // 2,
            0,
            line_thickness,
            handle_len_v,
        )

        self._size_grip.move(self.width() - self._size_grip.width(), self.height() - self._size_grip.height())

        corner_size = 18
        self._corner_resize_widgets["top_left"].setGeometry(0, 0, corner_size, corner_size)
        self._corner_resize_widgets["top_right"].setGeometry(
            max(0, self.width() - corner_size),
            0,
            corner_size,
            corner_size,
        )
        self._corner_resize_widgets["bottom_left"].setGeometry(
            0,
            max(0, self.height() - corner_size),
            corner_size,
            corner_size,
        )

        edge_thickness = 5
        top_w = max(0, self.width() - (2 * corner_size))
        bottom_w = top_w
        side_h = max(0, self.height() - (2 * corner_size))
        self._edge_resize_widgets["top"].setGeometry(corner_size, 0, top_w, edge_thickness)
        self._edge_resize_widgets["bottom"].setGeometry(
            corner_size,
            max(0, self.height() - edge_thickness),
            bottom_w,
            edge_thickness,
        )
        self._edge_resize_widgets["left"].setGeometry(0, corner_size, edge_thickness, side_h)
        self._edge_resize_widgets["right"].setGeometry(
            max(0, self.width() - edge_thickness),
            corner_size,
            edge_thickness,
            side_h,
        )
        self._corner_resize_widgets["bottom_right"].setGeometry(
            max(0, self.width() - corner_size),
            max(0, self.height() - corner_size),
            corner_size,
            corner_size,
        )
        self._close_button.raise_()
        overlay = getattr(self, "_review_slots_overlay", None)
        if overlay is not None:
            overlay_hint = overlay.sizeHint()
            overlay_w = int(overlay_hint.width())
            overlay_h = int(overlay_hint.height())
            show_overlay_geometry = (
                self._review_slots_enabled
                and self.width() >= overlay_w + (margin * 2)
                and self.height() >= overlay_h + self._close_button.height() + (margin * 2)
            )
            if show_overlay_geometry:
                overlay_x = max(margin, self.width() - overlay_w - margin - 1)
                overlay_y = min(
                    max(margin, close_y + self._close_button.height() + 8),
                    max(margin, self.height() - overlay_h - margin),
                )
                overlay.setGeometry(overlay_x, overlay_y, overlay_w, overlay_h)
                overlay.raise_()
            else:
                overlay.set_hover_active(False)

    def _show_close_button(self, visible: bool):
        if visible:
            self._close_button.show()
        else:
            self._close_button.hide()

    def _get_controls_rect_in_window(self) -> QRect | None:
        """Get current video-controls rect mapped to floating-window coordinates."""
        controls = getattr(self, "_video_controls_widget", None)
        if controls is None:
            return None
        try:
            if not controls.isVisible():
                return None
            top_left = controls.mapTo(self, QPoint(0, 0))
            return QRect(top_left, controls.size())
        except RuntimeError:
            return None

    def _is_handle_blocked_by_controls(self, handle_name: str) -> bool:
        """Handle must stay hidden when video controls overlap its area."""
        controls_rect = self._get_controls_rect_in_window()
        if controls_rect is None:
            return False
        zone = self._drag_handle_widgets.get(handle_name)
        if zone is None:
            return False
        return zone.geometry().intersects(controls_rect)

    def _show_drag_handle(self, handle_name: str, visible: bool):
        zone = self._drag_handle_widgets.get(handle_name)
        if zone is None:
            return
        if not self._uses_handle_only_window_drag():
            zone.hide()
            return
        if visible and not self._is_handle_blocked_by_controls(handle_name):
            zone.show()
        else:
            zone.hide()

    def _hide_all_drag_handles(self):
        for zone in self._drag_handle_widgets.values():
            zone.hide()

    def _is_in_close_hover_zone(self, local_pos: QPoint) -> bool:
        if local_pos.x() < 0 or local_pos.y() < 0:
            return False
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return False
        zone = self._close_hover_zone_px
        return local_pos.x() >= (self.width() - zone) and local_pos.y() <= zone

    def _hovered_drag_handles(self, local_pos: QPoint) -> set[str]:
        """Return edge handles hovered by cursor (excluding control-overlapped handles)."""
        hovered = set()
        if not self._uses_handle_only_window_drag():
            return hovered
        if local_pos.x() < 0 or local_pos.y() < 0:
            return hovered
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return hovered

        for name, zone in self._drag_handle_widgets.items():
            if self._is_handle_blocked_by_controls(name):
                continue
            hover_rect = zone.geometry().adjusted(
                -self._drag_hover_padding_px,
                -self._drag_hover_padding_px,
                self._drag_hover_padding_px,
                self._drag_hover_padding_px,
            )
            if hover_rect.contains(local_pos):
                hovered.add(name)
        return hovered

    def _update_overlay_hover_from_global_pos(self, global_pos: QPoint):
        local_pos = self.mapFromGlobal(global_pos)
        self._show_close_button(self._is_in_close_hover_zone(local_pos))
        self._update_shift_resize_visuals(global_pos)
        self._update_review_slots_hover(local_pos)
        if not self._uses_handle_only_window_drag():
            self._hide_all_drag_handles()
            return
        hovered_handles = self._hovered_drag_handles(local_pos)
        for name in self._drag_handle_widgets:
            should_show = (
                (self._window_drag_active and name == self._active_drag_handle)
                or (name in hovered_handles)
            )
            self._show_drag_handle(name, should_show)

    def _update_review_slots_hover(self, local_pos: QPoint):
        overlay = getattr(self, "_review_slots_overlay", None)
        if overlay is None:
            return
        should_show = (
            self._review_slots_enabled
            and local_pos.x() >= 0
            and local_pos.y() >= 0
            and local_pos.x() < self.width()
            and local_pos.y() < self.height()
            and not self._window_drag_active
            and not self._resize_active
            and not self._frozen_passthrough_mode
            and overlay.width() > 0
            and overlay.height() > 0
        )
        overlay.set_hover_active(bool(should_show))
        if should_show:
            overlay.refresh_state()

    def _show_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        exit_compare_action = None
        fit_mode_map = {}
        checker = getattr(self.viewer, "is_compare_mode_active", None)
        if callable(checker):
            try:
                if checker():
                    exit_compare_action = menu.addAction("Exit compare mode")
                    fit_mode_menu = menu.addMenu("Compare Fit Mode")
                    current_mode = None
                    get_mode = getattr(self.viewer, "get_compare_fit_mode", None)
                    if callable(get_mode):
                        try:
                            current_mode = get_mode()
                        except Exception:
                            current_mode = None
                    get_options = getattr(self.viewer, "get_compare_fit_mode_options", None)
                    if callable(get_options):
                        try:
                            for mode, label in get_options():
                                action = fit_mode_menu.addAction(str(label))
                                action.setCheckable(True)
                                action.setChecked(str(mode) == str(current_mode))
                                fit_mode_map[action] = str(mode)
                        except Exception:
                            pass
                    menu.addSeparator()
            except Exception:
                exit_compare_action = None
        sync_action = menu.addAction("Sync video")
        close_all_action = menu.addAction("Close all spawned viewers")
        selected = menu.exec(global_pos)
        if exit_compare_action is not None and selected is exit_compare_action:
            self.compare_exit_requested.emit(self.viewer)
        elif selected in fit_mode_map:
            setter = getattr(self.viewer, "set_compare_fit_mode", None)
            if callable(setter):
                try:
                    setter(fit_mode_map[selected], persist=True)
                except Exception:
                    pass
        elif selected is sync_action:
            self.sync_video_requested.emit()
        elif selected is close_all_action:
            self.close_all_requested.emit()

    def _apply_corner_resize(self, global_pos: QPoint):
        if not self._resize_active or not self._resize_corner:
            return
        self._update_shift_resize_visuals(global_pos)
        start = self._resize_start_geometry
        if not start.isValid():
            return

        dx = global_pos.x() - self._resize_start_global_pos.x()
        dy = global_pos.y() - self._resize_start_global_pos.y()

        x = start.x()
        y = start.y()
        w = start.width()
        h = start.height()

        min_w = max(10, self.minimumWidth())
        min_h = max(10, self.minimumHeight())

        preserve_aspect = False
        try:
            preserve_aspect = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        except Exception:
            preserve_aspect = False

        if preserve_aspect and start.height() > 0:
            aspect_ratio = start.width() / start.height()
            min_w = max(min_w, int(round(min_h * aspect_ratio)))
            min_h = max(min_h, int(round(min_w / aspect_ratio)))

            if self._resize_corner in ("left", "right"):
                raw_w = max(min_w, w - dx) if self._resize_corner == "left" else max(min_w, w + dx)
                w = raw_w
                h = max(min_h, int(round(w / aspect_ratio)))
                x = start.x() + (start.width() - w) if self._resize_corner == "left" else start.x()
                y = start.y() + ((start.height() - h) // 2)
                self.setGeometry(x, y, w, h)
                self._sync_viewer_scale_for_shift_resize(w, h)
                return

            if self._resize_corner in ("top", "bottom"):
                raw_h = max(min_h, h - dy) if self._resize_corner == "top" else max(min_h, h + dy)
                h = raw_h
                w = max(min_w, int(round(h * aspect_ratio)))
                x = start.x() + ((start.width() - w) // 2)
                y = start.y() + (start.height() - h) if self._resize_corner == "top" else start.y()
                self.setGeometry(x, y, w, h)
                self._sync_viewer_scale_for_shift_resize(w, h)
                return

            raw_w = w
            raw_h = h
            if self._resize_corner in ("top_left", "bottom_left"):
                raw_w = max(min_w, w - dx)
            elif self._resize_corner in ("top_right", "bottom_right"):
                raw_w = max(min_w, w + dx)

            if self._resize_corner in ("top_left", "top_right"):
                raw_h = max(min_h, h - dy)
            elif self._resize_corner in ("bottom_left", "bottom_right"):
                raw_h = max(min_h, h + dy)

            width_change = abs(raw_w - start.width())
            height_change = abs(raw_h - start.height())
            if width_change >= height_change:
                w = raw_w
                h = max(min_h, int(round(w / aspect_ratio)))
            else:
                h = raw_h
                w = max(min_w, int(round(h * aspect_ratio)))

            if self._resize_corner in ("top_left", "bottom_left"):
                x = start.x() + (start.width() - w)
            else:
                x = start.x()

            if self._resize_corner in ("top_left", "top_right"):
                y = start.y() + (start.height() - h)
            else:
                y = start.y()

            self.setGeometry(x, y, w, h)
            self._sync_viewer_scale_for_shift_resize(w, h)
            return

        if self._resize_corner in ("top_left", "bottom_left", "left"):
            new_w = max(min_w, w - dx)
            x = x + (w - new_w)
            w = new_w
        elif self._resize_corner in ("top_right", "bottom_right", "right"):
            w = max(min_w, w + dx)

        if self._resize_corner in ("top_left", "top_right", "top"):
            new_h = max(min_h, h - dy)
            y = y + (h - new_h)
            h = new_h
        elif self._resize_corner in ("bottom_left", "bottom_right", "bottom"):
            h = max(min_h, h + dy)

        self.setGeometry(x, y, w, h)

    def _sync_viewer_scale_for_shift_resize(self, width: int, height: int):
        """Scale manual zoom together with Shift-resize on spawned viewers."""
        if bool(getattr(self, "_resize_start_zoom_to_fit", True)):
            return

        viewer = getattr(self, "viewer", None)
        if viewer is None:
            return
        apply_zoom = getattr(viewer, "_apply_uniform_zoom_scale", None)
        if not callable(apply_zoom):
            return

        start = getattr(self, "_resize_start_geometry", QRect())
        if not start.isValid() or start.width() <= 0 or start.height() <= 0:
            return

        scale_ratio_w = float(width) / float(start.width())
        scale_ratio_h = float(height) / float(start.height())
        scale_ratio = min(scale_ratio_w, scale_ratio_h)
        if scale_ratio <= 0:
            return

        base_zoom = max(1e-9, float(getattr(self, "_resize_start_zoom_factor", 1.0) or 1.0))
        target_scale = max(1e-9, min(16.0, base_zoom * scale_ratio))

        try:
            current_scale = abs(float(viewer.view.transform().m11()))
        except Exception:
            current_scale = 0.0
        if current_scale > 0 and abs(current_scale - target_scale) <= max(1e-4, target_scale * 1e-4):
            return

        try:
            viewport = getattr(viewer, "view", None).viewport() if getattr(viewer, "view", None) is not None else None
            anchor_view_pos = viewport.rect().center() if viewport is not None else None
            focus_scene_pos = getattr(self, "_resize_start_focus_scene_pos", None)
            if focus_scene_pos is not None and hasattr(focus_scene_pos, "x") and hasattr(focus_scene_pos, "y"):
                apply_zoom(
                    target_scale,
                    zoom_to_fit_state=False,
                    focus_scene_pos=focus_scene_pos,
                    anchor_view_pos=anchor_view_pos,
                )
            else:
                apply_zoom(target_scale, zoom_to_fit_state=False)
        except Exception:
            pass

    def _set_view_resize_anchor_for_window_resize(self, active: bool):
        """Keep zoom stable while resizing the floating window."""
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(view, "setResizeAnchor"):
            return
        try:
            if active:
                if self._resize_prev_anchor is None:
                    try:
                        self._resize_prev_anchor = view.resizeAnchor()
                    except Exception:
                        self._resize_prev_anchor = QGraphicsView.ViewportAnchor.AnchorUnderMouse
                view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            else:
                restore_anchor = (
                    self._resize_prev_anchor
                    if self._resize_prev_anchor is not None
                    else QGraphicsView.ViewportAnchor.AnchorUnderMouse
                )
                view.setResizeAnchor(restore_anchor)
                self._resize_prev_anchor = None
        except Exception:
            self._resize_prev_anchor = None

    def _begin_window_resize(self, event, zone_name: str):
        if self._window_drag_active:
            self._cancel_compare_drag_signal()
        self._resize_active = True
        self._resize_corner = zone_name
        self._resize_start_geometry = self.geometry()
        self._resize_start_global_pos = self._event_global_pos(event)
        try:
            self._resize_start_zoom_factor = abs(float(self.viewer.view.transform().m11()))
        except Exception:
            self._resize_start_zoom_factor = 1.0
        if self._resize_start_zoom_factor <= 0:
            self._resize_start_zoom_factor = 1.0
        self._resize_start_zoom_to_fit = bool(getattr(self.viewer, "is_zoom_to_fit", True))
        try:
            view = getattr(self.viewer, "view", None)
            viewport = view.viewport() if view is not None else None
            if view is not None and viewport is not None:
                self._resize_start_focus_scene_pos = view.mapToScene(viewport.rect().center())
            else:
                self._resize_start_focus_scene_pos = QPointF()
        except Exception:
            self._resize_start_focus_scene_pos = QPointF()
        self._window_drag_active = False
        self._window_drag_button = Qt.MouseButton.NoButton
        self._active_drag_handle = None
        self._set_view_resize_anchor_for_window_resize(True)
        self._emit_activated()
        self._update_shift_resize_visuals(self._resize_start_global_pos)

    def _end_window_resize(self, event=None):
        self._resize_active = False
        self._resize_corner = None
        self._set_view_resize_anchor_for_window_resize(False)
        if event is not None:
            self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
        else:
            self._update_shift_resize_visuals(QCursor.pos())

    def _resize_zone_from_local_pos(self, local_pos: QPoint):
        """Return resize zone name from a local position near window borders."""
        margin = 12
        x = local_pos.x()
        y = local_pos.y()
        w = max(1, self.width())
        h = max(1, self.height())
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        near_left = x <= margin
        near_right = x >= (w - margin)
        near_top = y <= margin
        near_bottom = y >= (h - margin)

        if near_left and near_top:
            return "top_left"
        if near_right and near_top:
            return "top_right"
        if near_left and near_bottom:
            return "bottom_left"
        if near_right and near_bottom:
            return "bottom_right"
        if near_left:
            return "left"
        if near_right:
            return "right"
        if near_top:
            return "top"
        if near_bottom:
            return "bottom"
        return None

    def _cursor_for_resize_zone(self, zone_name: str | None):
        if zone_name in ("top_left", "bottom_right"):
            return Qt.CursorShape.SizeFDiagCursor
        if zone_name in ("top_right", "bottom_left"):
            return Qt.CursorShape.SizeBDiagCursor
        if zone_name in ("left", "right"):
            return Qt.CursorShape.SizeHorCursor
        if zone_name in ("top", "bottom"):
            return Qt.CursorShape.SizeVerCursor
        return None

    def eventFilter(self, watched, event):
        self._refresh_video_surface_event_filters()
        overlay = getattr(self, "_review_slots_overlay", None)
        if overlay is not None:
            try:
                if watched is overlay or overlay.isAncestorOf(watched):
                    return False
            except Exception:
                pass
        drag_sources = [self, self.viewer]
        if hasattr(self.viewer, "view"):
            drag_sources.append(self.viewer.view)
            drag_sources.append(self.viewer.view.viewport())
        drag_sources.extend(self._iter_video_surface_widgets())
        edge_name = self._edge_widget_to_edge.get(watched) if self._use_widget_resize_handles else None
        corner_name = self._corner_widget_to_corner.get(watched) if self._use_widget_resize_handles else None
        handle_name = self._drag_widget_to_handle.get(watched)

        if edge_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_window_resize(event, edge_name)
                return True
            if event.type() == QEvent.Type.MouseMove and self._resize_active:
                self._apply_corner_resize(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._resize_active:
                self._end_window_resize(event)
                return True
            if event.type() == QEvent.Type.Enter:
                self._emit_activated()
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif corner_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_window_resize(event, corner_name)
                return True
            if event.type() == QEvent.Type.MouseMove and self._resize_active:
                self._apply_corner_resize(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._resize_active:
                self._end_window_resize(event)
                return True
            if event.type() == QEvent.Type.Enter:
                self._emit_activated()
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif handle_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if not self._uses_handle_only_window_drag():
                    return True
                if self._is_handle_blocked_by_controls(handle_name):
                    return True
                self._begin_window_drag(event, handle_name)
                return True
            if (event.type() == QEvent.Type.MouseMove and self._is_window_drag_button_down(event)):
                global_pos = self._event_global_pos(event)
                self.move(global_pos - self._window_drag_offset)
                self._update_overlay_hover_from_global_pos(global_pos)
                if self._compare_drag_signal_active:
                    self.compare_drag_moved.emit(self, global_pos)
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and self._window_drag_active
                and event.button() == self._window_drag_button
            ):
                release_global = self._event_global_pos(event)
                self._window_drag_active = False
                self._window_drag_button = Qt.MouseButton.NoButton
                self._active_drag_handle = None
                self._update_overlay_hover_from_global_pos(release_global)
                if self._compare_drag_signal_active:
                    self._compare_drag_signal_active = False
                    self.compare_drag_released.emit(self, release_global)
                return True
            if event.type() == QEvent.Type.Enter:
                self._show_drag_handle(handle_name, True)
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif watched is getattr(self, "_video_controls_widget", None):
            if event.type() in (
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.Hide,
            ):
                self._update_overlay_hover_from_global_pos(QCursor.pos())
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                local_pos = self.mapFromGlobal(self._event_global_pos(event))
                zone_name = self._resize_zone_from_local_pos(local_pos)
                if zone_name is not None:
                    self._begin_window_resize(event, zone_name)
                    return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._emit_activated()
            elif event.type() == QEvent.Type.MouseMove:
                if self._resize_active:
                    self._apply_corner_resize(self._event_global_pos(event))
                    return True
                event_global = self._event_global_pos(event)
                try:
                    local_pos = self.mapFromGlobal(event_global)
                    zone_name = self._resize_zone_from_local_pos(local_pos)
                    resize_cursor = self._cursor_for_resize_zone(zone_name)
                    if resize_cursor is not None:
                        watched.setCursor(resize_cursor)
                        self._update_overlay_hover_from_global_pos(event_global)
                    else:
                        watched.unsetCursor()
                except Exception:
                    pass
                # Keep ownership switching click-free when hovering controls.
                self._force_activate_viewer_owner()
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._resize_active:
                    self._end_window_resize(event)
                    try:
                        watched.unsetCursor()
                    except Exception:
                        pass
                    return True
        elif watched in drag_sources:
            if event.type() == QEvent.Type.Enter:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self._emit_activated()
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._press_hits_marking(watched, event):
                        return False
                    zoom_handler = getattr(self.viewer, "apply_floating_double_click_zoom", None)
                    if callable(zoom_handler):
                        handled = False
                        scene_anchor = self._event_scene_pos(watched, event)
                        view_anchor = self._event_viewport_pos(watched, event)
                        try:
                            handled = bool(
                                zoom_handler(
                                    scene_anchor_pos=scene_anchor,
                                    view_anchor_pos=view_anchor,
                                )
                            )
                        except Exception:
                            handled = False
                        if handled:
                            self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                            return True
            elif event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._emit_activated()
                if event.button() == Qt.MouseButton.LeftButton:
                    zone_press_handler = getattr(self.viewer, "handle_video_surface_zone_press", None)
                    if callable(zone_press_handler):
                        try:
                            view_anchor = self._event_viewport_pos(watched, event)
                            if bool(zone_press_handler(view_anchor)):
                                self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                                return True
                        except Exception:
                            pass
                    local_pos = self.mapFromGlobal(self._event_global_pos(event))
                    zone_name = self._resize_zone_from_local_pos(local_pos)
                    if zone_name is not None:
                        self._begin_window_resize(event, zone_name)
                        return True
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._begin_window_drag(event, None)
                    return True
                if self._should_start_surface_window_drag(watched, event):
                    self._begin_window_drag(event, None)
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                zone_move_handler = getattr(self.viewer, "handle_video_surface_zone_move", None)
                if callable(zone_move_handler):
                    try:
                        if bool(zone_move_handler(self._event_viewport_pos(watched, event))):
                            self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                            return True
                    except Exception:
                        pass
                if self._resize_active:
                    self._apply_corner_resize(self._event_global_pos(event))
                    return True
                event_global = self._event_global_pos(event)
                # Force handoff on hover even if child event propagation differs.
                if self._video_controls_widget is not None:
                    try:
                        if self._video_controls_widget.geometry().adjusted(-20, -20, 20, 20).contains(
                            self.viewer.mapFromGlobal(event_global)
                        ):
                            self._force_activate_viewer_owner()
                    except Exception:
                        pass
                if self._is_window_drag_button_down(event):
                    self.move(event_global - self._window_drag_offset)
                    self._update_overlay_hover_from_global_pos(event_global)
                    if self._compare_drag_signal_active:
                        self.compare_drag_moved.emit(self, event_global)
                    return True
                try:
                    local_pos = self.mapFromGlobal(event_global)
                    zone_name = self._resize_zone_from_local_pos(local_pos)
                    resize_cursor = self._cursor_for_resize_zone(zone_name)
                    if resize_cursor is not None:
                        if hasattr(watched, "setCursor"):
                            watched.setCursor(resize_cursor)
                        self._update_overlay_hover_from_global_pos(event_global)
                        return False
                    if hasattr(watched, "unsetCursor"):
                        watched.unsetCursor()
                except Exception:
                    pass
                self._update_overlay_hover_from_global_pos(event_global)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                zone_release_handler = getattr(self.viewer, "handle_video_surface_zone_release", None)
                if callable(zone_release_handler):
                    try:
                        if bool(zone_release_handler(self._event_viewport_pos(watched, event))):
                            self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                            return True
                    except Exception:
                        pass
                if self._resize_active and event.button() == Qt.MouseButton.LeftButton:
                    self._end_window_resize(event)
                    try:
                        if hasattr(watched, "unsetCursor"):
                            watched.unsetCursor()
                    except Exception:
                        pass
                    return True
                if self._window_drag_active and event.button() == self._window_drag_button:
                    release_global = self._event_global_pos(event)
                    self._window_drag_active = False
                    self._window_drag_button = Qt.MouseButton.NoButton
                    self._active_drag_handle = None
                    self._update_overlay_hover_from_global_pos(release_global)
                    if self._compare_drag_signal_active:
                        self._compare_drag_signal_active = False
                        self.compare_drag_released.emit(self, release_global)
                    return True
            elif event.type() == QEvent.Type.FocusIn:
                self._emit_activated()
        elif watched is self and event.type() == QEvent.Type.WindowActivate:
            self._emit_activated()

        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            self._update_shift_resize_visuals(QCursor.pos())

        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        self._reposition_overlay_controls()
        self._update_overlay_hover_from_global_pos(QCursor.pos())
        super().resizeEvent(event)

    def enterEvent(self, event):
        self._update_overlay_hover_from_global_pos(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_close_button(False)
        if not self._window_drag_active:
            self._hide_all_drag_handles()
        if self._review_slots_overlay is not None:
            self._review_slots_overlay.set_hover_active(False)
        self._update_shift_resize_visuals(QPoint(-1, -1))
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._emit_activated()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self._emit_activated()
        super().focusInEvent(event)

    def closeEvent(self, event):
        if self._resize_active:
            self._end_window_resize()
        self._shift_resize_glow_timer.stop()
        self._cancel_compare_drag_signal()
        self.closing.emit(self.viewer)
        super().closeEvent(event)
