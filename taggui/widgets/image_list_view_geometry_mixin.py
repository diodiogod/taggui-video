from widgets.image_list_shared import *  # noqa: F401,F403
import math
from PySide6.QtCore import Property
from PySide6.QtWidgets import QMainWindow

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    _shiboken_is_valid = None


class _SpawnDragArrowOverlay(QWidget):
    """Top-level transparent overlay that draws a directional drag arrow."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._start_global = QPoint()
        self._end_global = QPoint()
        self._local_start = QPoint()
        self._local_end = QPoint()

    def set_points(self, start_global: QPoint, end_global: QPoint):
        self._start_global = QPoint(start_global)
        self._end_global = QPoint(end_global)

        margin = 24
        min_x = min(self._start_global.x(), self._end_global.x()) - margin
        min_y = min(self._start_global.y(), self._end_global.y()) - margin
        max_x = max(self._start_global.x(), self._end_global.x()) + margin
        max_y = max(self._start_global.y(), self._end_global.y()) + margin
        width = max(1, max_x - min_x)
        height = max(1, max_y - min_y)
        self.setGeometry(min_x, min_y, width, height)

        self._local_start = QPoint(self._start_global.x() - min_x, self._start_global.y() - min_y)
        self._local_end = QPoint(self._end_global.x() - min_x, self._end_global.y() - min_y)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        line_color = QColor(255, 92, 92, 230)
        glow_color = QColor(255, 60, 60, 120)

        # Soft glow under stroke
        glow_pen = QPen(glow_color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        painter.drawLine(self._local_start, self._local_end)

        # Main stroke
        pen = QPen(line_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(self._local_start, self._local_end)

        # Arrow head at current cursor side
        dx = float(self._local_end.x() - self._local_start.x())
        dy = float(self._local_end.y() - self._local_start.y())
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux

        head_len = 14.0
        head_half = 6.0
        tip = QPoint(int(self._local_end.x()), int(self._local_end.y()))
        back = QPoint(
            int(round(tip.x() - (ux * head_len))),
            int(round(tip.y() - (uy * head_len))),
        )
        left = QPoint(
            int(round(back.x() + (px * head_half))),
            int(round(back.y() + (py * head_half))),
        )
        right = QPoint(
            int(round(back.x() - (px * head_half))),
            int(round(back.y() - (py * head_half))),
        )

        painter.setBrush(line_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygon([tip, left, right]))
        super().paintEvent(event)


class _DragIndicatorWidget(QWidget):
    """Drag indicator styled like hidden window markers, sized to match thumbnail."""
    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._transition_progress = 0.0

    def get_transition_progress(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._transition_progress)))
        except Exception:
            return 0.0

    def set_transition_progress(self, value):
        try:
            progress = float(value)
        except Exception:
            progress = 0.0
        progress = max(0.0, min(1.0, progress))
        if abs(progress - float(getattr(self, "_transition_progress", 0.0) or 0.0)) <= 1e-4:
            return
        self._transition_progress = progress
        self.update()

    def reset_transition_progress(self):
        self.set_transition_progress(0.0)

    transitionProgress = Property(float, get_transition_progress, set_transition_progress)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = self.get_transition_progress()

        fill_fade_progress = min(1.0, max(0.0, progress / 0.24))
        background_alpha = int(round(200 * max(0.0, 1.0 - fill_fade_progress)))
        background_radius = max(2.0, 6.0 - (progress * 2.2))
        border_alpha = max(64, int(round(255 - (progress * 185))))
        border_width = max(0.55, 2.0 - (progress * 1.35))
        border_radius = max(1.5, 5.0 - (progress * 1.8))
        glow_alpha = max(0, int(round(100 * max(0.0, 1.0 - (progress * 1.7)))))
        glow_width = max(0.0, 1.0 - (progress * 0.85))
        glow_inset = 3 + int(round(progress * 2.0))
        glow_radius = max(1.0, 3.0 - (progress * 1.5))

        # Semi-transparent dark background
        if background_alpha > 0:
            painter.setBrush(QColor(40, 40, 40, background_alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), background_radius, background_radius)

        # Bright border
        border_pen = QPen(QColor(100, 180, 255, border_alpha))
        border_pen.setWidthF(border_width)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), border_radius, border_radius)

        # Inner glow
        if glow_alpha > 0 and glow_width > 0.05:
            glow_pen = QPen(QColor(150, 200, 255, glow_alpha))
            glow_pen.setWidthF(glow_width)
            painter.setPen(glow_pen)
            glow_rect = self.rect().adjusted(glow_inset, glow_inset, -glow_inset, -glow_inset)
            if glow_rect.width() > 0 and glow_rect.height() > 0:
                painter.drawRoundedRect(glow_rect, glow_radius, glow_radius)


class _MasonryReflowGuideOverlay(QWidget):
    """Viewport overlay that guides the eye to a selected item's new position."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._start_rect = QRect()
        self._end_rect = QRect()
        self._progress = 0.0
        self.hide()

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

    def clear(self):
        self._start_rect = QRect()
        self._end_rect = QRect()
        self._progress = 0.0
        self.hide()

    def set_guide(self, start_rect: QRect, end_rect: QRect):
        self._start_rect = QRect(start_rect)
        self._end_rect = QRect(end_rect)
        self._progress = 0.0
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.update()

    @staticmethod
    def _lerp_point(start: QPoint, end: QPoint, t: float) -> QPoint:
        return QPoint(
            int(round(start.x() + ((end.x() - start.x()) * t))),
            int(round(start.y() + ((end.y() - start.y()) * t))),
        )

    def _draw_runner_segment(self, painter: QPainter, start: QPoint, end: QPoint, head_t: float, span_t: float, pen: QPen):
        if span_t <= 0.0:
            return
        tail_t = max(0.0, head_t - span_t)
        if head_t <= tail_t:
            return
        painter.save()
        painter.setPen(pen)
        painter.drawLine(
            self._lerp_point(start, end, tail_t),
            self._lerp_point(start, end, head_t),
        )
        painter.restore()

    @staticmethod
    def _clamp_point_to_rect(point: QPoint, rect: QRect) -> QPoint:
        if not rect.isValid():
            return QPoint(point)
        return QPoint(
            max(rect.left(), min(rect.right(), point.x())),
            max(rect.top(), min(rect.bottom(), point.y())),
        )

    @classmethod
    def _clamp_rect_to_bounds(cls, rect: QRect, bounds: QRect) -> QRect:
        if not rect.isValid():
            return QRect()
        top_left = cls._clamp_point_to_rect(rect.topLeft(), bounds)
        bottom_right = cls._clamp_point_to_rect(rect.bottomRight(), bounds)
        return QRect(top_left, bottom_right).normalized()

    def _draw_target_brackets(self, painter: QPainter, rect: QRect, alpha_scale: float):
        if rect.width() <= 0 or rect.height() <= 0 or alpha_scale <= 0.0:
            return

        bracket_len = max(10, min(20, min(rect.width(), rect.height()) // 4))
        glow_pen = QPen(QColor(82, 255, 146, int(round(70 * alpha_scale))))
        glow_pen.setWidthF(7.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        base_pen = QPen(QColor(178, 255, 206, int(round(185 * alpha_scale))))
        base_pen.setWidthF(2.2)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        base_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        corners = (
            (QPoint(rect.left(), rect.top()), 1, 1),
            (QPoint(rect.right(), rect.top()), -1, 1),
            (QPoint(rect.left(), rect.bottom()), 1, -1),
            (QPoint(rect.right(), rect.bottom()), -1, -1),
        )

        for pen in (glow_pen, base_pen):
            painter.setPen(pen)
            for corner, x_dir, y_dir in corners:
                painter.drawLine(corner, QPoint(corner.x() + (bracket_len * x_dir), corner.y()))
                painter.drawLine(corner, QPoint(corner.x(), corner.y() + (bracket_len * y_dir)))

    def paintEvent(self, event):
        if not self._start_rect.isValid() or not self._end_rect.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        progress = self.get_progress()
        fade_out = 1.0 - max(0.0, (progress - 0.72) / 0.28)
        fade_out = max(0.0, min(1.0, fade_out))
        if fade_out <= 0.0:
            return

        safe_bounds = self.rect().adjusted(10, 10, -10, -10)
        clamped_end_rect = self._clamp_rect_to_bounds(self._end_rect.adjusted(1, 1, -1, -1), safe_bounds)
        start = self._clamp_point_to_rect(self._start_rect.center(), safe_bounds)
        end = self._clamp_point_to_rect(self._end_rect.center(), safe_bounds)
        dx = float(end.x() - start.x())
        dy = float(end.y() - start.y())
        distance = math.hypot(dx, dy)
        if distance <= 1.0:
            self._draw_target_brackets(painter, clamped_end_rect, fade_out)
            return

        path_glow_pen = QPen(QColor(64, 255, 136, int(round(38 * fade_out))))
        path_glow_pen.setWidthF(6.0)
        path_glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        path_glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path_pen = QPen(QColor(150, 255, 192, int(round(88 * fade_out))))
        path_pen.setWidthF(1.7)
        path_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        path_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(path_glow_pen)
        painter.drawLine(start, end)
        painter.setPen(path_pen)
        painter.drawLine(start, end)

        head_t = max(0.10, min(1.0, 0.14 + (progress * 0.86)))
        min_runner_pixels = 18.0
        max_runner_pixels = 52.0
        runner_span = min(
            0.92,
            max(
                0.18,
                min_runner_pixels / distance,
                min(0.34, max_runner_pixels / distance),
            ),
        )
        trail_specs = (
            (0.0, runner_span, QColor(214, 255, 222, int(round(170 * fade_out))), 7.0),
            (runner_span * 0.30, runner_span * 0.72, QColor(138, 255, 178, int(round(122 * fade_out))), 4.8),
            (runner_span * 0.58, runner_span * 0.40, QColor(86, 244, 140, int(round(76 * fade_out))), 3.0),
        )
        for offset, span, color, width_value in trail_specs:
            runner_pen = QPen(color)
            runner_pen.setWidthF(width_value)
            runner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            runner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self._draw_runner_segment(
                painter,
                start,
                end,
                max(0.0, head_t - offset),
                span,
                runner_pen,
            )

        bracket_progress = min(1.0, max(0.0, (progress - 0.16) / 0.34))
        self._draw_target_brackets(
            painter,
            clamped_end_rect,
            fade_out * (0.35 + (0.65 * bracket_progress)),
        )


class ImageListViewGeometryMixin:
    def _selected_masonry_viewport_rect(self, global_index: int, *, scroll_value: int | None = None) -> QRect:
        """Return a masonry item's rect in viewport coordinates."""
        if not (isinstance(global_index, int) and global_index >= 0):
            return QRect()
        rect = self._get_masonry_item_rect(int(global_index))
        if not rect.isValid():
            return QRect()
        if scroll_value is None:
            try:
                scroll_value = int(self.verticalScrollBar().value())
            except Exception:
                scroll_value = 0
        return rect.translated(0, -int(scroll_value or 0))

    def _capture_selected_reflow_guide_snapshot(self, source_model=None):
        """Capture the selected item's current viewport rect before masonry reflow."""
        if not (self.use_masonry and self._masonry_items):
            return None
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        resolver = getattr(self, "_get_current_or_selected_global_index", None)
        target_global = resolver(source_model=source_model) if callable(resolver) else getattr(self, "_selected_global_index", None)
        if not (isinstance(target_global, int) and target_global >= 0):
            return None

        viewport_rect = self.viewport().rect()
        item_rect = self._selected_masonry_viewport_rect(int(target_global))
        if not item_rect.isValid():
            return None
        if not item_rect.adjusted(-36, -36, 36, 36).intersects(viewport_rect):
            return None
        return {
            "global_index": int(target_global),
            "viewport_rect": QRect(item_rect),
        }

    def _show_selected_reflow_guide_from_snapshot(self, snapshot):
        """Animate a guide from the previous selected-item position to the new one."""
        if not isinstance(snapshot, dict):
            return
        target_global = snapshot.get("global_index")
        start_rect = snapshot.get("viewport_rect")
        if not (isinstance(target_global, int) and target_global >= 0):
            return
        if not isinstance(start_rect, QRect) or not start_rect.isValid():
            return

        end_rect = self._selected_masonry_viewport_rect(int(target_global))
        if not end_rect.isValid():
            return

        viewport_rect = self.viewport().rect()
        if not end_rect.adjusted(-24, -24, 24, 24).intersects(viewport_rect):
            return

        start_center = start_rect.center()
        end_center = end_rect.center()
        overlay = getattr(self, "_masonry_reflow_guide_overlay", None)
        if overlay is None:
            overlay = _MasonryReflowGuideOverlay(self.viewport())
            self._masonry_reflow_guide_overlay = overlay
        else:
            try:
                if overlay.parentWidget() is not self.viewport():
                    overlay.setParent(self.viewport())
            except Exception:
                pass

        animation = getattr(self, "_masonry_reflow_guide_animation", None)
        if animation is not None:
            try:
                animation.stop()
            except Exception:
                pass

        overlay.set_guide(start_rect, end_rect)

        from PySide6.QtCore import QEasingCurve, QPropertyAnimation

        animation = QPropertyAnimation(overlay, b"progress", self)
        animation.setDuration(560)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup():
            try:
                overlay.clear()
            except Exception:
                pass

        animation.finished.connect(_cleanup)
        self._masonry_reflow_guide_animation = animation
        animation.start()

    def _is_full_width_masonry_mode(self) -> bool:
        """Whether masonry currently owns the full workspace width."""
        if not self.use_masonry:
            return False
        host = self.window()
        if not isinstance(host, QMainWindow):
            return False
        return not bool(getattr(host, "_main_viewer_visible", True))

    def _resolve_full_width_masonry_thumbnail_size(self, target_size: int, zoom_direction: int = 0) -> int:
        """Resolve a target thumbnail size to the closest full-width exact-fit size."""
        metrics = self._get_masonry_column_metrics() if hasattr(self, "_get_masonry_column_metrics") else None
        if not metrics:
            return int(target_size)

        avail_width = int(metrics.get("avail_width", 0) or 0)
        spacing = int(metrics.get("spacing", 2) or 2)
        target_size = int(target_size or 0)
        min_size = int(getattr(self, "min_thumbnail_size", 16) or 16)
        max_size = int(getattr(self, "max_thumbnail_size", 512) or 512)
        if avail_width <= 0 or target_size <= 0:
            return max(min_size, min(max_size, target_size if target_size > 0 else min_size))

        zoom_direction = int(zoom_direction or 0)
        base = max(1.0, float(target_size + spacing))
        cols_exact = (float(avail_width + spacing) / base)

        if zoom_direction > 0:
            cols = max(1, int(math.floor(cols_exact)))
        elif zoom_direction < 0:
            cols = max(1, int(math.ceil(cols_exact)))
        else:
            cols = max(1, int(round(cols_exact)))

        max_cols = max(1, int((avail_width + spacing) // max(1, min_size + spacing)))
        cols = max(1, min(max_cols, cols))
        usable = avail_width - ((cols - 1) * spacing)
        if usable <= 0:
            return max(min_size, min(max_size, target_size))

        size = usable // cols
        return max(min_size, min(max_size, int(size)))

    def _quantize_full_width_masonry_thumbnail_size(self) -> bool:
        """Snap thumbnail size to the best-fit full-width masonry size."""
        if not self._is_full_width_masonry_mode():
            return False

        target_size = int(getattr(self, "_target_thumbnail_size", getattr(self, "current_thumbnail_size", 0)) or 0)
        zoom_direction = int(getattr(self, "_last_ctrl_wheel_zoom_direction", 0) or 0)
        best_size = self._resolve_full_width_masonry_thumbnail_size(target_size, zoom_direction)
        if best_size == int(getattr(self, "current_thumbnail_size", 0) or 0):
            return False

        self.current_thumbnail_size = int(best_size)
        self._target_thumbnail_size = int(target_size)
        self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))
        self._update_view_mode()
        parent_widget = self.parent()
        if parent_widget is not None and hasattr(parent_widget, 'update_thumbnail_size_controls'):
            parent_widget.update_thumbnail_size_controls()
        return True

    def _on_zoom_resize_idle_finished(self):
        """Allow a deferred snap only after Ctrl+wheel zoom has gone idle."""
        if not self.use_masonry:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_resize_idle_timer.start(250)
            return
        self._zoom_resize_snap_defer_until = 0.0
        self._zoom_resize_wait_for_ctrl_release = False
        self._quantize_full_width_masonry_thumbnail_size()
        self._on_resize_finished()

    def _snap_masonry_dock_to_columns(self) -> bool:
        """Shrink the dock to the exact width required for the current column count."""
        if not self.use_masonry:
            return False
        host = self.window()
        try:
            preserve_until = float(getattr(host, "_preserve_restored_dock_layout_until", 0.0) or 0.0)
        except Exception:
            preserve_until = 0.0
        if preserve_until > time.time():
            return False
        if bool(getattr(self, "_masonry_splitter_snapping", False)):
            self._masonry_splitter_snapping = False
            return False

        metrics = self._get_masonry_column_metrics() if hasattr(self, "_get_masonry_column_metrics") else None
        if not metrics:
            return False

        viewport_width = int(metrics.get("viewport_width", 0) or 0)
        content_width = int(metrics.get("content_width", 0) or 0)
        horizontal_padding = int(metrics.get("horizontal_padding", 0) or 0)
        spacing = int(metrics.get("spacing", 2) or 2)
        if viewport_width <= 0 or content_width <= 0:
            return False

        # Leave a few safety pixels above the exact threshold so the snapped
        # dock width keeps the intended column count even if resizeDocks lands
        # slightly short of the requested size.
        snap_safety_px = max(6, spacing * 3)
        target_viewport_width = content_width + horizontal_padding + snap_safety_px
        if target_viewport_width >= viewport_width:
            return False

        slack = viewport_width - target_viewport_width
        # Ignore tiny paint/frame noise; only snap meaningful dead space.
        if slack < max(8, spacing * 2):
            return False

        dock = self.parentWidget()
        while dock is not None and not isinstance(dock, QDockWidget):
            dock = dock.parentWidget()
        main_window = host
        if not isinstance(dock, QDockWidget):
            return False
        if not isinstance(main_window, QMainWindow):
            return False
        if dock.isFloating():
            return False

        current_dock_width = int(dock.width() or 0)
        if current_dock_width <= 0:
            return False

        chrome_width = max(0, current_dock_width - viewport_width)
        target_dock_width = chrome_width + target_viewport_width
        min_dock_width = max(int(dock.minimumWidth() or 0), target_dock_width)
        target_dock_width = max(min_dock_width, target_dock_width)
        if target_dock_width >= current_dock_width - 2:
            return False

        self._masonry_splitter_snapping = True
        main_window.resizeDocks([dock], [target_dock_width], Qt.Orientation.Horizontal)
        return True

    def _build_queues_async(self):
        """Build priority queues asynchronously (runs on next event loop to avoid blocking UI)."""
        source_model = self.model().sourceModel()
        if not source_model or not hasattr(source_model, 'PAGE_SIZE'):
            self._queue_building = False
            return
        is_paginated = bool(
            hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
        )
        total_count = (
            int(getattr(source_model, '_total_count', 0) or 0)
            if is_paginated
            else int(source_model.rowCount())
        )
        if total_count <= 0:
            self._queue_building = False
            return

        # Get visible items
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)
        visible_items = self._get_masonry_visible_items(viewport_rect)

        if not visible_items:
            self._queue_building = False
            return

        # Ignore virtual spacer items (-2/-3) used by strict/windowed masonry.
        # Using them here corrupts queue centering and can preload far pages.
        visible_indices = []
        for item in visible_items:
            idx = item.get('index', -1)
            if isinstance(idx, int) and 0 <= idx < total_count:
                visible_indices.append(idx)

        # If only spacers are visible (rare edge frames), fall back to current page.
        if not visible_indices:
            page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
            current_page = int(getattr(self, '_current_page', 0) or 0)
            center_idx = max(0, min(total_count - 1, (current_page * page_size) + (page_size // 2)))
            half_span = max(20, page_size // 12)
            start = max(0, center_idx - half_span)
            end = min(total_count - 1, center_idx + half_span)
            visible_indices = list(range(start, end + 1))

        min_visible = min(visible_indices)
        max_visible = max(visible_indices)
        mid_visible = (min_visible + max_visible) // 2
        visible_count = len(visible_indices)

        # Update model with visible indices for enrichment prioritization
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if source_model and hasattr(source_model, 'set_visible_indices'):
            source_model.set_visible_indices(set(visible_indices))

        # Buffer sizes
        near_buffer_size = max(visible_count * 2, 100)
        far_buffer_size = max(visible_count * 3, 150)

        # Predictive loading based on scroll direction
        if self._scroll_direction == 'down':
            near_buffer_below = int(near_buffer_size * 1.5)
            near_buffer_above = int(near_buffer_size * 0.5)
            far_buffer_below = int(far_buffer_size * 1.5)
            far_buffer_above = int(far_buffer_size * 0.5)
        elif self._scroll_direction == 'up':
            near_buffer_below = int(near_buffer_size * 0.5)
            near_buffer_above = int(near_buffer_size * 1.5)
            far_buffer_below = int(far_buffer_size * 0.5)
            far_buffer_above = int(far_buffer_size * 1.5)
        else:
            near_buffer_below = near_buffer_above = near_buffer_size // 2
            far_buffer_below = far_buffer_above = far_buffer_size // 2

        # Clear old queues and build new ones
        self._urgent_queue = []
        self._high_queue = []
        self._low_queue = []
        visited = set()

        # ZONE 1: Urgent (visible items, center-outward)
        self._urgent_queue.append(mid_visible)
        visited.add(mid_visible)
        offset = 1
        while len(visited) < visible_count:
            if mid_visible + offset <= max_visible and mid_visible + offset not in visited:
                self._urgent_queue.append(mid_visible + offset)
                visited.add(mid_visible + offset)
            if mid_visible - offset >= min_visible and mid_visible - offset not in visited:
                self._urgent_queue.append(mid_visible - offset)
                visited.add(mid_visible - offset)
            offset += 1
            if offset > visible_count + 10:
                break

        # ZONE 2: High (near buffer)
        for i in range(max_visible + 1, min(max_visible + near_buffer_below + 1, total_count)):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)
        for i in range(min_visible - 1, max(0, min_visible - near_buffer_above) - 1, -1):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)

        # ZONE 3: Low (far buffer)
        far_start_below = max_visible + near_buffer_below + 1
        for i in range(far_start_below, min(far_start_below + far_buffer_below, total_count)):
            if i not in visited:
                self._low_queue.append(i)
                visited.add(i)
        far_start_above = min_visible - near_buffer_above - 1
        for i in range(far_start_above, max(0, far_start_above - far_buffer_above) - 1, -1):
            if i not in visited:
                self._low_queue.append(i)
                visited.add(i)

        # Update legacy queue
        self._pagination_preload_queue = self._urgent_queue + self._high_queue + self._low_queue

        # Track queue center
        self._last_queue_center = scroll_offset + viewport_height // 2

        # Mark building complete
        self._queue_building = False

        # Trigger immediate preload
        self._idle_preload_timer.stop()
        self._idle_preload_timer.start(0)


    def _evict_distant_thumbnails(self):
        """Evict thumbnails that are far from current viewport (VRAM management)."""
        source_model = self.model().sourceModel()
        if not source_model:
            return

        # Get current visible range
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)
        visible_items = self._get_masonry_visible_items(viewport_rect)

        if not visible_items:
            return

        visible_indices = set(item['index'] for item in visible_items)
        min_visible = min(visible_indices)
        max_visible = max(visible_indices)

        # Keep items within N pages of visible area (configurable for VRAM management)
        eviction_pages = settings.value('thumbnail_eviction_pages', defaultValue=3, type=int)
        eviction_pages = max(1, min(eviction_pages, 5))  # Clamp to 1-5
        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        is_paginated = bool(
            hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
        )
        total_count = (
            int(getattr(source_model, '_total_count', 0) or 0)
            if is_paginated
            else int(source_model.rowCount())
        )
        if total_count <= 0:
            return

        keep_range_start = max(0, min_visible - page_size * eviction_pages)
        keep_range_end = min(total_count - 1, max_visible + page_size * eviction_pages)

        # Evict thumbnails outside keep range
        evicted_count = 0
        if is_paginated and hasattr(source_model, '_pages'):
            lock = getattr(source_model, '_page_load_lock', None)
            if lock:
                with lock:
                    pages_snapshot = list(source_model._pages.items())
            else:
                pages_snapshot = list(source_model._pages.items())

            for page_num, page in pages_snapshot:
                if not page:
                    continue
                base_idx = int(page_num) * page_size
                for offset, image in enumerate(page):
                    if image is None:
                        continue
                    global_idx = base_idx + offset
                    if global_idx < keep_range_start or global_idx > keep_range_end:
                        if image.thumbnail or image.thumbnail_qimage:
                            image.thumbnail = None
                            image.thumbnail_qimage = None
                            evicted_count += 1
                            # Pagination preload tracks global indices.
                            if hasattr(self, '_pagination_loaded_items'):
                                self._pagination_loaded_items.discard(global_idx)
        else:
            for i, image in enumerate(source_model.images):
                if i < keep_range_start or i > keep_range_end:
                    if image.thumbnail or image.thumbnail_qimage:
                        image.thumbnail = None
                        image.thumbnail_qimage = None
                        evicted_count += 1
                        if hasattr(self, '_pagination_loaded_items'):
                            self._pagination_loaded_items.discard(i)

        if evicted_count > 0:
            print(f"[EVICT] Evicted {evicted_count} distant thumbnails (keeping indices {keep_range_start}-{keep_range_end})")


    def _show_thumbnail_progress(self, total_items):
        """Show progress bar for thumbnail loading."""
        if not self._thumbnail_progress_bar:
            self._thumbnail_progress_bar = QProgressBar(self.viewport())
            self._thumbnail_progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid #555;
                    border-radius: 5px;
                    background-color: rgba(0, 0, 0, 180);
                    text-align: center;
                    color: white;
                    font-size: 12px;
                    min-height: 20px;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                    border-radius: 3px;
                }
            """)

        self._thumbnail_progress_bar.setMaximum(total_items)
        self._thumbnail_progress_bar.setValue(0)
        # Initial message - will update based on cache hit rate
        self._thumbnail_progress_bar.setFormat("Loading thumbnails: %v/%m")
        self._update_progress_bar_position()
        self._thumbnail_progress_bar.show()
        self._thumbnail_progress_bar.raise_()


    def _update_progress_bar_position(self):
        """Update progress bar position to follow viewport (stick to bottom)."""
        if self._thumbnail_progress_bar and self._thumbnail_progress_bar.isVisible():
            # Position at bottom of viewport (follows scroll)
            bar_width = min(300, self.viewport().width() - 20)
            self._thumbnail_progress_bar.setGeometry(
                (self.viewport().width() - bar_width) // 2,
                self.viewport().height() - 40,
                bar_width,
                25
            )
            self._thumbnail_progress_bar.raise_()  # Keep on top


    def _update_thumbnail_progress(self, current, total):
        """Update progress bar value and message based on cache performance."""
        if self._thumbnail_progress_bar:
            self._thumbnail_progress_bar.setValue(current)

            # Update message based on cache hit rate
            total_processed = len(self._thumbnail_cache_hits) + len(self._thumbnail_cache_misses)
            if total_processed > 10:  # Wait for at least 10 samples
                cache_rate = (len(self._thumbnail_cache_hits) / total_processed) * 100

                # Calculate how many are loading vs generating
                cached_count = len(self._thumbnail_cache_hits)
                generating_count = len(self._thumbnail_cache_misses)

                if cache_rate > 95:
                    # Almost all cached - fast loading
                    self._thumbnail_progress_bar.setFormat("Updating dimensions: %v/%m")
                elif cache_rate < 20:
                    # Almost all generating - slow
                    self._thumbnail_progress_bar.setFormat("Generating: %v/%m")
                else:
                    # Mixed - show both counts with color coding
                    self._thumbnail_progress_bar.setFormat(
                        f"Updating dimensions: {cached_count} | Generating: {generating_count} (%v/%m)"
                    )
            else:
                # Not enough data yet, use neutral message
                self._thumbnail_progress_bar.setFormat("Updating dimensions: %v/%m")


    def _hide_thumbnail_progress(self):
        """Hide progress bar when complete."""
        if self._thumbnail_progress_bar:
            # Fade out effect
            QTimer.singleShot(500, self._thumbnail_progress_bar.hide)  # Hide after 500ms

    def _invalidate_pending_masonry_for_mode_switch(self):
        """Invalidate in-flight masonry work when switching List/Icon mode."""
        self._masonry_mode_generation = int(getattr(self, "_masonry_mode_generation", 0)) + 1
        self._masonry_calculating = False
        self._masonry_recalc_pending = False
        if hasattr(self, "_masonry_recalc_timer"):
            self._masonry_recalc_timer.stop()
        if hasattr(self, "_resize_timer"):
            self._resize_timer.stop()


    def _apply_startup_view_mode_seed(self):
        """Seed startup mode before hysteresis logic runs."""
        saved_mode = str(settings.value("image_list_view_mode", "", type=str) or "").strip().lower()
        model = self.model()
        source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        paginated_source = bool(
            source_model
            and hasattr(source_model, "_paginated_mode")
            and source_model._paginated_mode
        )
        if saved_mode == "list":
            self.use_virtual_list = paginated_source
            self.setViewMode(
                QListView.ViewMode.IconMode
                if paginated_source
                else QListView.ViewMode.ListMode
            )
            return
        if saved_mode == "icon":
            self.use_virtual_list = False
            self.setViewMode(QListView.ViewMode.IconMode)
            return

        threshold = int(getattr(self, "column_switch_threshold", 150) or 150)
        if int(getattr(self, "current_thumbnail_size", 0) or 0) >= threshold:
            self.use_virtual_list = paginated_source
            self.setViewMode(
                QListView.ViewMode.IconMode
                if paginated_source
                else QListView.ViewMode.ListMode
            )
        else:
            self.use_virtual_list = False
            self.setViewMode(QListView.ViewMode.IconMode)


    def _persist_current_view_mode(self):
        """Persist active mode so startup hysteresis can use the right prior mode."""
        mode_value = (
            "list"
            if bool(getattr(self, "use_virtual_list", False))
            or self.viewMode() == QListView.ViewMode.ListMode
            else "icon"
        )
        try:
            existing = str(settings.value("image_list_view_mode", "", type=str) or "")
            if existing != mode_value:
                settings.setValue("image_list_view_mode", mode_value)
        except Exception:
            pass


    def _update_view_mode(self):
        """Switch between single column (ListMode) and multi-column (IconMode) based on thumbnail size."""
        import time
        previous_mode = self.viewMode()
        previous_virtual_list = bool(getattr(self, "use_virtual_list", False))
        now = time.time()
        hysteresis = int(getattr(self, "_view_mode_hysteresis_px", 30) or 30)
        cooldown_s = float(getattr(self, "_view_mode_switch_cooldown_s", 0.35) or 0.35)
        threshold = int(getattr(self, "column_switch_threshold", 150) or 150)
        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), 'sourceModel')
            else self.model()
        )
        paginated_source = bool(
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        )

        # Use hysteresis to avoid rapid toggling around threshold.
        was_list_state = bool(
            previous_virtual_list or previous_mode == QListView.ViewMode.ListMode
        )
        if was_list_state:
            switch_to_list = self.current_thumbnail_size > max(self.min_thumbnail_size, threshold - hysteresis)
        else:
            switch_to_list = self.current_thumbnail_size >= threshold
        switch_to_virtual_list = bool(switch_to_list and paginated_source)
        desired_qt_mode = (
            QListView.ViewMode.IconMode
            if (switch_to_virtual_list or not switch_to_list)
            else QListView.ViewMode.ListMode
        )
        mode_state_changed = (
            desired_qt_mode != previous_mode
            or previous_virtual_list != switch_to_virtual_list
        )
        if mode_state_changed:
            force_virtual_enable = bool(
                switch_to_virtual_list and not previous_virtual_list
            )
            if (
                (not force_virtual_enable)
                and (now - float(getattr(self, "_last_view_mode_switch_time", 0.0) or 0.0)) < cooldown_s
            ):
                # Keep current mode during cooldown to avoid unsafe mode churn.
                self.use_virtual_list = previous_virtual_list
                self.use_masonry = (
                    previous_mode == QListView.ViewMode.IconMode
                    and not previous_virtual_list
                )
                self._persist_current_view_mode()
                return
            self._last_view_mode_switch_time = now

        if switch_to_list:
            # Large thumbnails: native list for in-memory datasets, virtual
            # fixed-row list for paginated datasets.
            self.use_virtual_list = switch_to_virtual_list
            self.use_masonry = False
            if switch_to_virtual_list:
                if previous_mode != QListView.ViewMode.IconMode or not previous_virtual_list:
                    self._invalidate_pending_masonry_for_mode_switch()
                if previous_mode != QListView.ViewMode.IconMode:
                    self.setViewMode(QListView.ViewMode.IconMode)
                self.setFlow(QListView.Flow.TopToBottom)
                self.setResizeMode(QListView.ResizeMode.Fixed)
                self.setWrapping(False)
                self.setSpacing(0)
                self.setGridSize(QSize(-1, -1))
                # Initialize fixed-row virtual scrollbar domain immediately.
                # Without this, Qt can keep a temporary loaded-row range until a
                # later layout event, which looks like a ~4k "fake end" that
                # then expands while scrolling.
                self.updateGeometries()
                if previous_mode != QListView.ViewMode.IconMode or not previous_virtual_list:
                    QTimer.singleShot(0, self._scroll_selected_global_to_center_safe)
                self.viewport().update()
            else:
                if previous_mode != QListView.ViewMode.ListMode or previous_virtual_list:
                    self._invalidate_pending_masonry_for_mode_switch()
                if previous_mode != QListView.ViewMode.ListMode:
                    self.setViewMode(QListView.ViewMode.ListMode)
                self.setFlow(QListView.Flow.TopToBottom)
                self.setResizeMode(QListView.ResizeMode.Adjust)
                self.setWrapping(False)
                self.setSpacing(0)
                self.setGridSize(QSize(-1, -1))  # Reset grid size to default

                # Re-center selected item when switching to ListMode
                if previous_mode != QListView.ViewMode.ListMode or previous_virtual_list:
                    QTimer.singleShot(0, self._scroll_current_index_to_center_safe)
        else:
            # Small thumbnails: masonry grid view (Pinterest-style)
            self.use_virtual_list = False
            self.use_masonry = True
            if previous_mode != QListView.ViewMode.IconMode or previous_virtual_list:
                self._invalidate_pending_masonry_for_mode_switch()
            if previous_mode != QListView.ViewMode.IconMode:
                self.setViewMode(QListView.ViewMode.IconMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setResizeMode(QListView.ResizeMode.Fixed)
            self.setWrapping(True)
            self.setSpacing(2)
            self.setUniformItemSizes(False)  # Allow varying sizes
            # Disable default grid - we'll handle positioning with masonry
            self.setGridSize(QSize(-1, -1))
            # Calculate masonry layout (will re-center via flag)
            self._recenter_after_layout = (previous_mode != QListView.ViewMode.IconMode)
            self._calculate_masonry_layout()
            # Force item delegate to recalculate sizes and update viewport
            self.scheduleDelayedItemsLayout()
            self.viewport().update()

        self._persist_current_view_mode()

    def _virtual_list_is_active(self, source_model=None) -> bool:
        """Return True when paginated list mode should use custom virtual scrolling."""
        if bool(getattr(self, "use_masonry", False)):
            return False
        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        paginated = bool(
            source_model
            and hasattr(source_model, "_paginated_mode")
            and source_model._paginated_mode
        )
        if not paginated:
            return False
        # Accept either explicit virtual-list flag or native ListMode fallback.
        # This prevents transient mode-state mismatches from dropping back to
        # rowCount-based native scrollbar math in paginated folders.
        return bool(
            getattr(self, "use_virtual_list", False)
            or self.viewMode() == QListView.ViewMode.ListMode
        )

    def _virtual_list_row_height(self) -> int:
        """Fixed row height for virtual list mode."""
        try:
            icon_width = int(self.iconSize().width())
        except Exception:
            icon_width = int(getattr(self, "current_thumbnail_size", 96) or 96)
        return max(48, icon_width + 4)

    def _virtual_list_total_height(self, source_model=None) -> int:
        """Total virtual content height for paginated list mode."""
        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if not source_model:
            return 0
        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            return 0
        return total_items * self._virtual_list_row_height()

    def _ensure_virtual_list_visible_range_loaded(self, source_model=None, extra_rows: int | None = None):
        """Request the currently visible virtual-list rows plus a small buffer."""
        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if not self._virtual_list_is_active(source_model):
            return
        if not source_model or not hasattr(source_model, "ensure_pages_for_range"):
            return

        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            return

        row_height = max(1, self._virtual_list_row_height())
        viewport_height = max(1, int(self.viewport().height()))
        scroll_offset = max(0, int(self.verticalScrollBar().value()))
        start_row = max(0, scroll_offset // row_height)
        end_row = min(
            total_items - 1,
            (scroll_offset + viewport_height + row_height - 1) // row_height,
        )
        if extra_rows is None:
            extra_rows = max(6, viewport_height // row_height)
        start_row = max(0, start_row - int(extra_rows))
        end_row = min(total_items - 1, end_row + int(extra_rows))
        if hasattr(source_model, "set_page_protection_window") and hasattr(source_model, "PAGE_SIZE"):
            try:
                page_size = max(1, int(source_model.PAGE_SIZE))
                last_page = max(0, (total_items - 1) // page_size)
                start_page = max(0, min(start_row // page_size, last_page))
                end_page = max(0, min(end_row // page_size, last_page))
                source_model.set_page_protection_window(
                    max(0, start_page - 1),
                    min(last_page, end_page + 1),
                )
            except Exception:
                pass
        source_model.ensure_pages_for_range(start_row, end_row)


    def _resolve_live_spawn_index(self, dragged_index: QPersistentModelIndex, dragged_path) -> QModelIndex:
        """Resolve a live proxy index after drag, with path fallback for churn."""
        try:
            live_index = self.model().index(dragged_index.row(), dragged_index.column())
        except Exception:
            live_index = QModelIndex()

        if (not live_index.isValid()) and dragged_path is not None:
            try:
                proxy_model = self.model()
                source_model = proxy_model.sourceModel() if hasattr(proxy_model, "sourceModel") else None
                if source_model is not None and hasattr(source_model, "get_index_for_path"):
                    src_row = source_model.get_index_for_path(dragged_path)
                    if isinstance(src_row, int) and src_row >= 0:
                        src_idx = source_model.index(src_row, 0)
                        if src_idx.isValid() and hasattr(proxy_model, "mapFromSource"):
                            live_index = proxy_model.mapFromSource(src_idx)
            except Exception:
                live_index = QModelIndex()
        return live_index

    def _spawn_floating_from_drag_index(
        self,
        live_index: QModelIndex,
        source_pixmap: QPixmap,
        spawn_global_pos: QPoint | None = None,
    ):
        """Spawn one floating viewer from resolved proxy index."""
        if not live_index.isValid():
            hide_ghost = getattr(self, "_hide_spawn_drag_ghost", None)
            if callable(hide_ghost):
                hide_ghost()
            return False
        spawn_point = spawn_global_pos if spawn_global_pos is not None else QCursor.pos()
        main_window = self.window()
        if not (main_window and hasattr(main_window, 'spawn_floating_viewer_at')):
            hide_ghost = getattr(self, "_hide_spawn_drag_ghost", None)
            if callable(hide_ghost):
                hide_ghost()
            return False

        drag_spawn_size_fraction = 0.40
        preview_started = False
        try:
            preview_rect = QRect()
            if hasattr(main_window, "_get_initial_floating_size"):
                try:
                    spawn_w, spawn_h = main_window._get_initial_floating_size(
                        live_index,
                        aspect_ratio_override=None,
                        size_fraction=drag_spawn_size_fraction,
                    )
                    preview_rect = QRect(
                        spawn_point.x() - spawn_w // 2,
                        spawn_point.y() - spawn_h // 2,
                        spawn_w,
                        spawn_h,
                    )
                except Exception:
                    preview_rect = QRect()
            if preview_rect.isValid():
                try:
                    preview_started = bool(
                        self._flash_drag_drop_preview(
                            preview_rect,
                            fallback_size=self._pixmap_logical_size(source_pixmap),
                        )
                    )
                except Exception:
                    preview_started = False
            main_window.spawn_floating_viewer_at(
                target_index=live_index,
                spawn_global_pos=spawn_point,
                initial_size_fraction=drag_spawn_size_fraction,
            )
            return True
        except Exception as e:
            print(f"[DRAG-SPAWN] Spawn warning: {e}")
            return False
        finally:
            if not preview_started:
                hide_ghost = getattr(self, "_hide_spawn_drag_ghost", None)
                if callable(hide_ghost):
                    hide_ghost()

    def _build_spawn_drag_source_pixmap(self, model_index: QModelIndex) -> QPixmap:
        """Build a best-effort thumbnail pixmap for drag ghost/preview."""
        source_pixmap = QPixmap()
        try:
            icon = model_index.data(Qt.ItemDataRole.DecorationRole)
            if icon is not None:
                source_pixmap = icon.pixmap(self.iconSize())
        except Exception:
            source_pixmap = QPixmap()
        if source_pixmap.isNull():
            try:
                item_rect = self.visualRect(model_index)
                if item_rect.isValid() and item_rect.width() > 0 and item_rect.height() > 0:
                    source_pixmap = self.viewport().grab(item_rect)
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            fallback_side = max(48, int(self.iconSize().width() or 96))
            source_pixmap = QPixmap(fallback_side, fallback_side)
            source_pixmap.fill(Qt.GlobalColor.transparent)
        return source_pixmap

    def _pixmap_logical_size(self, pixmap: QPixmap) -> QSize:
        """Return display-space size for a pixmap, honoring device-pixel ratio."""
        if pixmap is None or pixmap.isNull():
            return QSize()
        try:
            logical_size = pixmap.deviceIndependentSize()
            return QSize(
                max(1, int(round(logical_size.width()))),
                max(1, int(round(logical_size.height()))),
            )
        except Exception:
            dpr = max(1.0, float(pixmap.devicePixelRatio() or 1.0))
            return QSize(
                max(1, int(round(pixmap.width() / dpr))),
                max(1, int(round(pixmap.height() / dpr))),
            )

    def _show_spawn_drag_ghost(self, model_index: QModelIndex):
        """Show drag indicator sized to match thumbnail."""
        if not model_index.isValid():
            return
        source_pixmap = self._build_spawn_drag_source_pixmap(model_index)
        if source_pixmap.isNull():
            return

        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is None:
            ghost = _DragIndicatorWidget(None)
            self._spawn_drag_ghost_widget = ghost

        # Size to match the thumbnail
        ghost_size = self._pixmap_logical_size(source_pixmap)
        if not ghost_size.isValid():
            ghost_size = source_pixmap.size()
        ghost.resize(ghost_size)
        self._spawn_drag_ghost_size = QSize(ghost_size)
        try:
            ghost.reset_transition_progress()
        except Exception:
            pass
        ghost.show()
        ghost.raise_()
        self._update_spawn_drag_ghost_pos()

    def _update_spawn_drag_ghost_pos(self, global_pos: QPoint | None = None):
        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is None:
            return
        cursor_global = global_pos if global_pos is not None else QCursor.pos()
        # Center the top-level indicator on the global cursor position.
        size = getattr(self, '_spawn_drag_ghost_size', QSize(40, 40))
        ghost.move(cursor_global.x() - size.width() // 2, cursor_global.y() - size.height() // 2)

        try:
            self._spawn_drag_last_global_pos = QPoint(cursor_global)
        except Exception:
            pass

    def _hide_spawn_drag_ghost(self):
        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is not None:
            try:
                ghost.reset_transition_progress()
            except Exception:
                pass
            ghost.hide()

    def _show_spawn_drag_arrow(self, start_global: QPoint, end_global: QPoint):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is None:
            overlay = _SpawnDragArrowOverlay()
            self._spawn_drag_arrow_overlay = overlay
        overlay.set_points(start_global, end_global)
        overlay.show()

    def _update_spawn_drag_arrow(self, start_global: QPoint, end_global: QPoint):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is None:
            return
        overlay.set_points(start_global, end_global)

    def _hide_spawn_drag_arrow(self):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is not None:
            overlay.hide()

    def _spawn_floating_for_index_at_cursor(
        self,
        model_index: QModelIndex,
        spawn_global_pos: QPoint | None = None,
    ):
        """Spawn directly at cursor from one explicit index (no Qt drag loop)."""
        if not model_index.isValid():
            return False
        dragged_index = QPersistentModelIndex(model_index)
        dragged_path = None
        try:
            image = model_index.data(Qt.ItemDataRole.UserRole)
            dragged_path = getattr(image, "path", None)
        except Exception:
            dragged_path = None

        source_pixmap = self._build_spawn_drag_source_pixmap(model_index)

        live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
        return self._spawn_floating_from_drag_index(
            live_index,
            source_pixmap,
            spawn_global_pos=spawn_global_pos,
        )

    def _start_spawn_drag_for_index(self, model_index: QModelIndex, supportedActions: Qt.DropAction):
        """Start drag/spawn flow from one explicit index (selection-independent)."""
        if not model_index.isValid():
            return
        external_only = bool(
            hasattr(self, "_drag_to_external_only_mode")
            and self._drag_to_external_only_mode()
        )
        indices = [model_index]
        dragged_index = QPersistentModelIndex(model_index)
        dragged_path = None
        try:
            image = model_index.data(Qt.ItemDataRole.UserRole)
            dragged_path = getattr(image, "path", None)
        except Exception:
            dragged_path = None

        # Use an URLs-only payload for external file drags. Some targets (notably
        # browsers) mis-handle the model's text/plain fallback as dropped text.
        if external_only and dragged_path is not None:
            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(str(dragged_path))])
        else:
            mime_data = self.model().mimeData(indices)
        if not mime_data:
            return

        # Build a reliable visual preview pixmap.
        source_pixmap = QPixmap()
        icon = model_index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            try:
                source_pixmap = icon.pixmap(self.iconSize())
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            try:
                item_rect = self.visualRect(indices[0])
                if item_rect.isValid() and item_rect.width() > 0 and item_rect.height() > 0:
                    source_pixmap = self.viewport().grab(item_rect)
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            fallback_side = max(48, int(self.iconSize().width() or 96))
            source_pixmap = QPixmap(fallback_side, fallback_side)
            source_pixmap.fill(Qt.GlobalColor.transparent)

        # Drag pixmap is slightly translucent for ghosting.
        drag_pixmap = QPixmap(source_pixmap.size())
        drag_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(drag_pixmap)
        painter.setOpacity(0.86)
        painter.drawPixmap(0, 0, source_pixmap)
        painter.end()

        # Ultra-fast drag/release race: if button is already up by the time we
        # reach drag start, skip QDrag.exec() and spawn immediately.
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            if not external_only:
                live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
                self._spawn_floating_from_drag_index(live_index, source_pixmap)
            return

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(drag_pixmap)
        drag.setHotSpot(drag_pixmap.rect().center())
        drop_action = drag.exec(supportedActions)

        # If dropped onto no external target, spawn a floating viewer at cursor.
        if (
            drop_action == Qt.DropAction.IgnoreAction
            and dragged_index.isValid()
            and not external_only
        ):
            live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
            self._spawn_floating_from_drag_index(live_index, source_pixmap)

    def startDrag(self, supportedActions: Qt.DropAction):
        indices = self.selectedIndexes()
        if not indices:
            return
        # Keep Qt override behavior, but route through explicit-index path.
        self._start_spawn_drag_for_index(indices[0], supportedActions)

    def _flash_drag_drop_preview(self, target_rect: QRect, fallback_size: QSize | None = None):
        """Animate the current drag-frame overlay into the spawned viewer footprint."""
        if not target_rect.isValid():
            return False

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRect, QParallelAnimationGroup
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        overlay = getattr(self, "_spawn_drag_ghost_widget", None)
        overlay_owned = False
        start_rect = QRect()
        if overlay is not None:
            try:
                if overlay.isVisible():
                    start_rect = QRect(overlay.geometry())
            except RuntimeError:
                overlay = None
                start_rect = QRect()
        if overlay is None:
            overlay = _DragIndicatorWidget(None)
            overlay_owned = True

        if not start_rect.isValid():
            start_size = fallback_size if isinstance(fallback_size, QSize) else QSize()
            start_w = max(1, int(start_size.width()))
            start_h = max(1, int(start_size.height()))
            if start_w <= 1 and start_h <= 1:
                start_w = max(40, min(target_rect.width(), 96))
                start_h = max(40, min(target_rect.height(), 96))
            center_pos = target_rect.center()
            start_rect = QRect(
                center_pos.x() - start_w // 2,
                center_pos.y() - start_h // 2,
                start_w,
                start_h,
            )
            overlay.setGeometry(start_rect)

        overlay.show()
        overlay.raise_()
        try:
            overlay.reset_transition_progress()
        except Exception:
            pass

        opacity_effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(opacity_effect)

        animation_group = QParallelAnimationGroup(self)

        fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
        fade_animation.setDuration(230)
        fade_animation.setStartValue(1.0)
        fade_animation.setKeyValueAt(0.78, 1.0)
        fade_animation.setEndValue(0.0)
        fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        scale_animation = QPropertyAnimation(overlay, b"geometry")
        scale_animation.setDuration(230)
        scale_animation.setStartValue(start_rect)
        scale_animation.setEndValue(target_rect)
        scale_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        style_animation = QPropertyAnimation(overlay, b"transitionProgress")
        style_animation.setDuration(230)
        style_animation.setStartValue(0.0)
        style_animation.setEndValue(1.0)
        style_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        animation_group.addAnimation(fade_animation)
        animation_group.addAnimation(scale_animation)
        animation_group.addAnimation(style_animation)
        if not hasattr(self, "_active_drag_preview_animations"):
            self._active_drag_preview_animations = []
        self._active_drag_preview_animations.append(animation_group)

        def _cleanup():
            try:
                if animation_group in self._active_drag_preview_animations:
                    self._active_drag_preview_animations.remove(animation_group)
            except Exception:
                pass
            try:
                overlay.setGraphicsEffect(None)
            except Exception:
                pass
            try:
                overlay.reset_transition_progress()
            except Exception:
                pass
            if overlay_owned:
                overlay.deleteLater()
            else:
                overlay.hide()

        animation_group.finished.connect(_cleanup)
        animation_group.start()
        return True


    def resizeEvent(self, event):
        """Recalculate masonry layout on resize (debounced)."""
        super().resizeEvent(event)
        if self.use_masonry:
            if getattr(self, '_skip_next_resize_recalc', False):
                # This flag is meant to skip one stale *queued* recalc after a
                # click/zoom anchor cancellation. If we keep returning here, all
                # future resize-driven recalcs can be blocked until Ctrl+wheel
                # clears the flag. Consume it and continue with this real resize.
                self._skip_next_resize_recalc = False
            import time
            if time.time() <= float(getattr(self, '_restore_anchor_until', 0.0) or 0.0):
                # Startup restore in progress: skip resize-driven recalc churn.
                return
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            if hasattr(self, '_activate_resize_anchor'):
                self._activate_resize_anchor(source_model=source_model, hold_s=3.0)
            # Debounce resize-triggered masonry recalcs enough to avoid
            # repeated strict-window ownership churn while dragging.
            self._resize_timer.stop()
            self._resize_timer.start(140)


    def _on_resize_finished(self):
        """Called after resize stops (debounced)."""
        if self.use_masonry:
            if getattr(self, '_skip_next_resize_recalc', False):
                self._skip_next_resize_recalc = False
                return
            import time
            if time.time() <= float(getattr(self, '_restore_anchor_until', 0.0) or 0.0):
                return
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
            strict_paginated = bool(
                source_model
                and hasattr(source_model, '_paginated_mode')
                and source_model._paginated_mode
                and strategy == "windowed_strict"
            )

            if strict_paginated:
                if hasattr(self, '_activate_resize_anchor'):
                    self._activate_resize_anchor(source_model=source_model, hold_s=2.0)
            else:
                self._resize_anchor_page = None
                self._resize_anchor_target_global = None
                self._resize_anchor_until = 0.0

            ctrl_active = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
            zoom_snap_waiting = bool(getattr(self, "_zoom_resize_wait_for_ctrl_release", False))
            zoom_idle_pending = bool(
                hasattr(self, "_zoom_resize_idle_timer")
                and self._zoom_resize_idle_timer.isActive()
            )
            import time
            if (
                (ctrl_active and zoom_snap_waiting)
                or (zoom_snap_waiting and zoom_idle_pending)
                or time.time() < float(getattr(self, "_zoom_resize_snap_defer_until", 0.0) or 0.0)
            ):
                # Ctrl+wheel zoom should relayout thumbnails without repeatedly
                # resizing the dock. Snap only after zoom input has been idle.
                self._recenter_after_layout = not strict_paginated
                self._last_masonry_window_signature = None
                self._last_masonry_signal = "zoom_resize"
                self._calculate_masonry_layout()
                self.viewport().update()
                return

            mouse_buttons = QApplication.mouseButtons()
            dragging_splitter = bool(mouse_buttons & Qt.MouseButton.LeftButton)
            if dragging_splitter:
                # Keep live masonry updates while the splitter moves, but do not
                # snap until the drag is actually finished.
                self._recenter_after_layout = not strict_paginated
                self._last_masonry_window_signature = None
                self._last_masonry_signal = "resize_drag"
                self._calculate_masonry_layout()
                self.viewport().update()
                self._resize_timer.stop()
                self._resize_timer.start(90)
                return

            explicit_thumbnail_resize = (
                getattr(self, "_last_masonry_signal", None) == "thumbnail_size_button"
            )
            if (
                (not explicit_thumbnail_resize)
                and (not self._is_full_width_masonry_mode())
                and self._snap_masonry_dock_to_columns()
            ):
                return

            # In strict paginated mode, explicit page/global anchoring above is
            # more stable than recentering via possibly stale proxy row index.
            self._recenter_after_layout = not strict_paginated
            self._last_masonry_window_signature = None
            if not explicit_thumbnail_resize:
                self._last_masonry_signal = "resize"
            self._calculate_masonry_layout()
            self.viewport().update()


    def viewportSizeHint(self):
        """Return the size hint for masonry layout."""
        if self.use_masonry and self._masonry_items:
            size = self._get_masonry_total_size()
            # Debug: check if Qt is using this to calculate scrollbar
            # print(f"[VIEWPORT HINT] Returning size: {size.width()}x{size.height()}")
            return size
        return super().viewportSizeHint()


    def updateGeometries(self):
        """Override to prevent Qt from resetting scrollbar in buffered pagination mode."""
        import time
        # Use stable proxy reference
        source_model = None
        if hasattr(self, 'proxy_image_list_model') and self.proxy_image_list_model:
             source_model = self.proxy_image_list_model.sourceModel()
    
        if not source_model:
             source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
         
        is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        strict_mode = strategy == "windowed_strict"

        # If we have a huge height calculated, assume buffered mode even if check fails transiently
        force_buffered = hasattr(self, '_masonry_total_height') and self._masonry_total_height > 50000

        # print(f"[TEMP_DEBUG] UpdateGeom: is_buffered={is_buffered}, force={force_buffered}, height={getattr(self, '_masonry_total_height', '?')}")

        if is_buffered and self._virtual_list_is_active(source_model):
            sb = self.verticalScrollBar()
            old_value = int(sb.value())
            viewport_height = max(1, int(self.viewport().height()))
            correct_max = max(0, self._virtual_list_total_height(source_model) - viewport_height)
            prev_block = sb.blockSignals(True)
            try:
                sb.setSingleStep(max(8, self._virtual_list_row_height() // 3))
                sb.setPageStep(viewport_height)
                sb.setRange(0, correct_max)
                # Virtual list is exact fixed-row math; preserve current scroll
                # position directly and only clamp to the valid range.
                target_value = old_value
                sb.setValue(max(0, min(target_value, correct_max)))
            finally:
                sb.blockSignals(prev_block)
            self._last_stable_scroll_value = int(sb.value())
            self._ensure_virtual_list_visible_range_loaded(source_model=source_model)
            self.viewport().update()
            return

        if (is_buffered or force_buffered) and self.use_masonry:
            # Buffered mode: preserve our manually-set scrollbar range
            # Qt would reset it based on rowCount(), which is wrong for virtual pagination
            old_max = self.verticalScrollBar().maximum()
            old_value = self.verticalScrollBar().value()

            # Store the correct range before Qt messes with it
            if hasattr(self, '_masonry_total_height') and self._masonry_total_height > 0:
                viewport_height = self.viewport().height()
                correct_max = max(0, self._masonry_total_height - viewport_height)
            else:
                correct_max = old_max
        
            # print(f"[TEMP_DEBUG] UpdateGeom: CorrectMax={correct_max}, OldMax={old_max}")

            if strict_mode:
                _log_idle_strict = (not self._mouse_scrolling) and (not self._scrollbar_dragging)
                def _strict_tail_scroll_target():
                    try:
                        total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                        if total_items_i <= 0 or not self._masonry_items:
                            return None
                        tail_idx = total_items_i - 1
                        tail_item = None
                        for _it in self._masonry_items:
                            if int(_it.get('index', -1)) == tail_idx:
                                tail_item = _it
                                break
                        if tail_item is None:
                            return None
                        tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                        return max(0, tail_bottom - max(1, self.viewport().height()))
                    except Exception:
                        return None

                # Block signals through the entire strict correction to prevent
                # _on_scroll_value_changed from recording transient values.
                saved_val = self.verticalScrollBar().value()
                saved_max = max(1, self.verticalScrollBar().maximum())
                _click_scroll_freeze = (
                    time.time()
                    < float(getattr(self, '_user_click_selection_frozen_until', 0.0) or 0.0)
                )
                self.verticalScrollBar().blockSignals(True)
                try:
                    super().updateGeometries()
                    keep_max = self._strict_canonical_domain_max(source_model)
                    if self._scrollbar_dragging or self._drag_preview_mode:
                        self._restore_strict_drag_domain(source_model=source_model)
                    elif _click_scroll_freeze:
                        # User recently clicked — update range but keep value.
                        self.verticalScrollBar().setRange(0, keep_max)
                        if getattr(self, '_stick_to_edge', None) == "bottom":
                            _tail_target = _strict_tail_scroll_target()
                            if _tail_target is not None:
                                self.verticalScrollBar().setValue(max(0, min(_tail_target, keep_max)))
                            else:
                                self.verticalScrollBar().setValue(max(0, min(saved_val, keep_max)))
                        elif getattr(self, '_stick_to_edge', None) == "top":
                            self.verticalScrollBar().setValue(0)
                        else:
                            self.verticalScrollBar().setValue(max(0, min(saved_val, keep_max)))
                    else:
                        self.verticalScrollBar().setRange(0, keep_max)
                        # Re-anchor to locked page so thumb stays put when domain grows.
                        _rl_page = getattr(self, '_release_page_lock_page', None)
                        _rl_live = (
                            _rl_page is not None
                            and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        _ps = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                        _ti = int(getattr(source_model, '_total_count', 0) or 0)
                        _last_page = max(0, (_ti - 1) // max(1, _ps)) if _ti > 0 else 0
                        if _rl_live and keep_max > 0:
                            if getattr(self, '_stick_to_edge', None) == "bottom" or int(_rl_page) >= _last_page:
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    restored_val = max(0, min(_tail_target, keep_max))
                                else:
                                    restored_val = keep_max
                            elif getattr(self, '_stick_to_edge', None) == "top":
                                restored_val = 0
                            else:
                                _lock_idx = int(_rl_page) * _ps
                                _lock_it = None
                                for _it in self._masonry_items:
                                    if _it.get('index', -1) >= _lock_idx:
                                        _lock_it = _it
                                        break
                                if _lock_it is not None:
                                    restored_val = max(0, min(int(_lock_it['y']), keep_max))
                                else:
                                    _pf = max(0.0, min(1.0, _lock_idx / max(1, _ti)))
                                    restored_val = max(0, min(int(round(_pf * keep_max)), keep_max))
                        else:
                            restore_target = (
                                self._get_restore_anchor_scroll_value(source_model, keep_max)
                                if hasattr(self, '_get_restore_anchor_scroll_value')
                                else None
                            )
                            if restore_target is not None:
                                restored_val = max(0, min(int(restore_target), keep_max))
                            elif getattr(self, '_stick_to_edge', None) == "bottom":
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    restored_val = max(0, min(_tail_target, keep_max))
                                else:
                                    restored_val = keep_max
                            elif getattr(self, '_stick_to_edge', None) == "top":
                                restored_val = 0
                            else:
                                # Preserve absolute scroll value (clamped).
                                restored_val = max(0, min(saved_val, keep_max))
                        if self.verticalScrollBar().value() != restored_val:
                            self.verticalScrollBar().setValue(restored_val)
                finally:
                    self.verticalScrollBar().blockSignals(False)
                if _log_idle_strict and hasattr(self, "_log_diag"):
                    _sb = self.verticalScrollBar()
                    new_val = int(_sb.value())
                    new_max = int(_sb.maximum())
                    if abs(new_val - int(old_value)) > 1 or abs(new_max - int(old_max)) > 1:
                        self._log_diag(
                            "geom.strict_adjust",
                            source_model=source_model,
                            throttle_key="diag_geom_strict_adjust",
                            every_s=0.15,
                            extra=(
                                f"old={int(old_value)}/{int(old_max)} "
                                f"new={new_val}/{new_max} "
                                f"correct_max={int(correct_max)}"
                            ),
                        )
            else:
                super().updateGeometries()
                new_max = self.verticalScrollBar().maximum()
                if correct_max > 0 and new_max != correct_max:
                    self.verticalScrollBar().setRange(0, correct_max)
                    # Restore scroll position using STABLE memory
                    suppress_restore = time.time() < getattr(self, '_suppress_anchor_until', 0.0)
                    if getattr(self, '_stick_to_edge', None) == "bottom":
                        self.verticalScrollBar().setValue(correct_max)
                    elif getattr(self, '_stick_to_edge', None) == "top":
                        self.verticalScrollBar().setValue(0)
                    elif suppress_restore:
                        pass
                    elif hasattr(self, '_last_stable_scroll_value') and self._last_stable_scroll_value > 0 and self._last_stable_scroll_value <= correct_max:
                        if abs(self.verticalScrollBar().value() - self._last_stable_scroll_value) > 10:
                            self.verticalScrollBar().setValue(self._last_stable_scroll_value)
                    # Restore scroll position if Qt clamped it during range reduction (fallback)
                    elif (not suppress_restore) and self.verticalScrollBar().value() != old_value and old_value <= correct_max:
                        self.verticalScrollBar().blockSignals(True)
                        self.verticalScrollBar().setValue(old_value)
                        self.verticalScrollBar().blockSignals(False)

            # Enforce explicit edge lock even when range didn't change.
            if getattr(self, '_stick_to_edge', None) == "bottom":
                if strict_mode:
                    try:
                        _tail_target = None
                        _ti = int(getattr(source_model, '_total_count', 0) or 0)
                        if _ti > 0 and self._masonry_items:
                            _tail_idx = _ti - 1
                            _tail_item = None
                            for _it in self._masonry_items:
                                if int(_it.get('index', -1)) == _tail_idx:
                                    _tail_item = _it
                                    break
                            if _tail_item is not None:
                                _tail_bottom = int(_tail_item.get('y', 0)) + int(_tail_item.get('height', 0))
                                _tail_target = max(0, _tail_bottom - max(1, self.viewport().height()))
                        if _tail_target is not None:
                            self.verticalScrollBar().setValue(max(0, min(_tail_target, self.verticalScrollBar().maximum())))
                        else:
                            self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
                    except Exception:
                        self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
                else:
                    self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
            elif getattr(self, '_stick_to_edge', None) == "top":
                self.verticalScrollBar().setValue(0)
        else:
            # Normal mode: let Qt manage scrollbar
            super().updateGeometries()


    def _normalize_scroll_index(self, index) -> QModelIndex:
        """Return a model-owned index safe to pass into Qt scroll APIs."""
        model = self.model()
        if model is None:
            return QModelIndex()
        if index is None or not hasattr(index, "isValid"):
            return QModelIndex()
        try:
            # Never construct QPersistentModelIndex from a possibly stale Qt index:
            # this path has triggered native access violations during startup restore.
            if not index.isValid():
                return QModelIndex()
        except Exception:
            return QModelIndex()
        try:
            # Reject stale indices from old/different models to avoid Qt crashes.
            idx_model = index.model()
            if idx_model is not model:
                return QModelIndex()
        except Exception:
            return QModelIndex()
        try:
            row = int(index.row())
            col = int(index.column())
        except Exception:
            return QModelIndex()
        try:
            row_count = int(model.rowCount())
            col_count = int(model.columnCount())
        except Exception:
            return QModelIndex()
        if row < 0 or row >= row_count:
            return QModelIndex()
        col_count = max(1, col_count)
        if col < 0 or col >= col_count:
            col = 0
        try:
            resolved = model.index(row, col)
        except Exception:
            return QModelIndex()
        return resolved if resolved.isValid() else QModelIndex()

    def _proxy_index_to_global_index(self, index) -> int:
        """Map a proxy index to a stable global index in paginated mode."""
        safe_index = self._normalize_scroll_index(index)
        if not safe_index.isValid():
            return -1

        model = self.model()
        if model is None:
            return -1
        source_model = model.sourceModel() if hasattr(model, "sourceModel") else model

        try:
            source_index = model.mapToSource(safe_index) if hasattr(model, "mapToSource") else safe_index
        except Exception:
            source_index = QModelIndex()
        if not source_index.isValid():
            return -1

        if source_model and hasattr(source_model, "get_global_index_for_row"):
            try:
                mapped = source_model.get_global_index_for_row(source_index.row())
                return int(mapped) if isinstance(mapped, int) and mapped >= 0 else -1
            except Exception:
                return -1

        try:
            return int(source_index.row())
        except Exception:
            return -1

    def _scroll_current_index_to_center_safe(self):
        idx = self._normalize_scroll_index(self.currentIndex())
        if not idx.isValid():
            return
        self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _scroll_selected_global_to_center_safe(self):
        """Center virtual-list viewport on stable selected global index."""
        model = self.model()
        source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if not self._virtual_list_is_active(source_model):
            self._scroll_current_index_to_center_safe()
            return

        total_items = int(getattr(source_model, "_total_count", 0) or 0) if source_model else 0
        if total_items <= 0:
            return

        target_global = getattr(self, "_selected_global_index", None)
        if not (isinstance(target_global, int) and target_global >= 0):
            target_global = self._proxy_index_to_global_index(self.currentIndex())
        if not isinstance(target_global, int) or target_global < 0:
            return

        target_global = max(0, min(int(target_global), total_items - 1))
        row_height = max(1, self._virtual_list_row_height())
        viewport_h = max(1, int(self.viewport().height()))
        virtual_max = max(0, (total_items * row_height) - viewport_h)
        target_scroll = max(
            0,
            min(
                (target_global * row_height) - max(0, (viewport_h - row_height) // 2),
                virtual_max,
            ),
        )

        sb = self.verticalScrollBar()
        prev_block = sb.blockSignals(True)
        try:
            if int(sb.maximum()) != virtual_max:
                sb.setRange(0, virtual_max)
            sb.setValue(int(target_scroll))
        finally:
            sb.blockSignals(prev_block)
        self._last_stable_scroll_value = int(sb.value())

        if source_model and hasattr(source_model, "ensure_pages_for_range"):
            try:
                source_model.ensure_pages_for_range(int(target_global), int(target_global))
            except Exception:
                pass
        if hasattr(self, "_rebind_current_index_to_selected_global"):
            try:
                self._rebind_current_index_to_selected_global(source_model=source_model)
            except Exception:
                pass
        self.viewport().update()

    def scrollTo(self, index, hint=None):
        """Override scrollTo to use masonry positions instead of Qt's row-based layout.

        Qt calls this internally from setCurrentIndex(), which knows nothing
        about masonry coordinates.  Without this override, clicking an item
        triggers scrollTo → Qt computes scroll from row number → viewport
        jumps to the wrong position.
        """
        if hint is None:
            hint = QAbstractItemView.ScrollHint.EnsureVisible

        if _shiboken_is_valid is not None:
            try:
                if not _shiboken_is_valid(self):
                    return
            except Exception:
                return

        safe_index = self._normalize_scroll_index(index)
        if not safe_index.isValid():
            return

        # During model reset/layout churn, skip Qt scroll calls to avoid transient
        # C++ crashes from stale indices delivered by deferred restore callbacks.
        if getattr(self, "_model_resetting", False):
            return

        if self._virtual_list_is_active():
            if bool(getattr(self, "_suppress_virtual_auto_scroll_once", False)):
                if hint in (
                    QAbstractItemView.ScrollHint.EnsureVisible,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                ):
                    self._suppress_virtual_auto_scroll_once = False
                    return
            global_idx = self._proxy_index_to_global_index(safe_index)
            if global_idx < 0:
                return
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            row_height = self._virtual_list_row_height()
            item_top = global_idx * row_height
            item_bot = item_top + row_height
            sb = self.verticalScrollBar()
            scroll_val = int(sb.value())
            viewport_h = max(1, int(self.viewport().height()))
            virtual_max = max(0, self._virtual_list_total_height(source_model) - viewport_h)
            if sb.maximum() != virtual_max:
                prev_block = sb.blockSignals(True)
                try:
                    sb.setRange(0, virtual_max)
                finally:
                    sb.blockSignals(prev_block)

            if hint == QAbstractItemView.ScrollHint.EnsureVisible:
                if item_top >= scroll_val and item_bot <= scroll_val + viewport_h:
                    return
                if item_top < scroll_val:
                    new_val = max(0, min(item_top, virtual_max))
                    self._last_stable_scroll_value = new_val
                    sb.setValue(new_val)
                elif item_bot > scroll_val + viewport_h:
                    new_val = max(0, min(item_bot - viewport_h, virtual_max))
                    self._last_stable_scroll_value = new_val
                    sb.setValue(new_val)
            elif hint == QAbstractItemView.ScrollHint.PositionAtCenter:
                target = max(0, item_top - max(0, (viewport_h - row_height) // 2))
                new_val = max(0, min(target, virtual_max))
                self._last_stable_scroll_value = new_val
                sb.setValue(new_val)
            elif hint == QAbstractItemView.ScrollHint.PositionAtTop:
                new_val = max(0, min(item_top, virtual_max))
                self._last_stable_scroll_value = new_val
                sb.setValue(new_val)
            elif hint == QAbstractItemView.ScrollHint.PositionAtBottom:
                new_val = max(0, min(item_bot - viewport_h, virtual_max))
                self._last_stable_scroll_value = new_val
                sb.setValue(new_val)
            self._ensure_virtual_list_visible_range_loaded()
            return

        if not (self.use_masonry and self._masonry_items):
            try:
                model = self.model()
                if model is None:
                    return
                if safe_index.model() is not model:
                    return
                if safe_index.row() < 0 or safe_index.row() >= int(model.rowCount()):
                    return
                super().scrollTo(safe_index, hint)
            except Exception:
                # Ignore transient model/layout churn during view-mode switches.
                pass
            return

        # Map proxy row → global index → masonry rect.
        global_idx = safe_index.row()
        source_model = (
            self.model().sourceModel()
            if hasattr(self.model(), 'sourceModel')
            else self.model()
        )
        if source_model and hasattr(source_model, 'get_global_index_for_row'):
            global_idx = source_model.get_global_index_for_row(safe_index.row())
        elif source_model and getattr(source_model, '_paginated_mode', False):
            global_idx = self._map_row_to_global_index_safely(safe_index.row())

        rect = self._get_masonry_item_rect(global_idx)
        if not rect.isValid():
            return  # Item not in current masonry window — don't jump blindly.

        sb = self.verticalScrollBar()
        scroll_val = sb.value()
        vh = self.viewport().height()
        item_top = rect.y()
        item_bot = rect.y() + rect.height()

        if hint == QAbstractItemView.ScrollHint.EnsureVisible:
            # Already fully visible → do nothing.
            if item_top >= scroll_val and item_bot <= scroll_val + vh:
                return
            # Partially above → scroll up just enough.
            if item_top < scroll_val:
                sb.setValue(max(0, item_top))
            # Partially below → scroll down just enough.
            elif item_bot > scroll_val + vh:
                sb.setValue(max(0, item_bot - vh))
        elif hint == QAbstractItemView.ScrollHint.PositionAtCenter:
            center_y = item_top + rect.height() // 2
            target = max(0, center_y - vh // 2)
            sb.setValue(min(target, sb.maximum()))
        elif hint == QAbstractItemView.ScrollHint.PositionAtTop:
            sb.setValue(max(0, min(item_top, sb.maximum())))
        elif hint == QAbstractItemView.ScrollHint.PositionAtBottom:
            sb.setValue(max(0, min(item_bot - vh, sb.maximum())))

    def visualRect(self, index):
        """Return the visual rectangle for an index, using masonry positions."""
        if self.use_masonry and self._drag_preview_mode:
            return super().visualRect(index)
        if self._virtual_list_is_active() and index.isValid():
            global_idx = self._proxy_index_to_global_index(index)
            if global_idx < 0:
                return QRect()
            row_height = self._virtual_list_row_height()
            scroll_offset = int(self.verticalScrollBar().value())
            return QRect(
                0,
                (global_idx * row_height) - scroll_offset,
                max(1, int(self.viewport().width())),
                row_height,
            )
        if self.use_masonry and self._masonry_items and index.isValid():
            # In masonry mode, we map rows to global indices
            global_idx = index.row()
            if hasattr(self.model(), 'sourceModel'):
                source_model = self.model().sourceModel()
                if hasattr(source_model, 'get_global_index_for_row'):
                    global_idx = source_model.get_global_index_for_row(index.row())
                elif getattr(source_model, '_paginated_mode', False):
                    # Fallback mapping for paginated mode
                    global_idx = self._map_row_to_global_index_safely(index.row())

            # Get masonry position (absolute coordinates)
            rect = self._get_masonry_item_rect(global_idx)
            if rect.isValid():
                # Create new rect adjusted for scroll position (viewport coordinates)
                scroll_offset = self.verticalScrollBar().value()
                return QRect(rect.x(), rect.y() - scroll_offset, rect.width(), rect.height())
            return QRect()
        else:
            # Use default positioning
            return super().visualRect(index)


    def indexAt(self, point):
        """Return the index at the given point, using masonry positions.

        Prefers the painted-geometry snapshot when fresh so that hit-testing
        matches what the user actually sees (immune to async recalc swaps).
        """
        if self.use_masonry and self._drag_preview_mode:
            return super().indexAt(point)
        if self._virtual_list_is_active():
            if point.x() < 0 or point.x() > self.viewport().width():
                return QModelIndex()
            source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
            total_items = int(getattr(source_model, '_total_count', 0) or 0) if source_model else 0
            if total_items <= 0:
                return QModelIndex()
            row_height = max(1, self._virtual_list_row_height())
            scroll_offset = int(self.verticalScrollBar().value())
            global_idx = (int(point.y()) + scroll_offset) // row_height
            if global_idx < 0 or global_idx >= total_items:
                return QModelIndex()
            proxy_idx = self._proxy_index_from_global(global_idx)
            if proxy_idx.isValid():
                return proxy_idx
            self._ensure_virtual_list_visible_range_loaded(
                source_model=source_model,
                extra_rows=max(4, int(self.viewport().height()) // row_height),
            )
            return QModelIndex()
        if self.use_masonry and self._masonry_items:
            import time as _t
            source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()

            hit_global = -1

            # 1. Try painted snapshot first (matches what user sees).
            #    Use the scroll offset captured at paint time, not the current
            #    value — updateGeometries() can shift it between paints.
            painted = getattr(self, '_painted_hit_regions', None)
            painted_age = _t.time() - float(getattr(self, '_painted_hit_regions_time', 0.0) or 0.0)
            if painted and painted_age < 2.0:
                snap_scroll = int(getattr(self, '_painted_hit_regions_scroll_offset', 0) or 0)
                adjusted_point = QPoint(point.x(), point.y() + snap_scroll)
                for g_idx, rect in painted.items():
                    if rect.contains(adjusted_point):
                        hit_global = int(g_idx)
                        break

            # 2. Fallback to live masonry index map.
            if hit_global < 0:
                scroll_offset = self.verticalScrollBar().value()
                adjusted_point = QPoint(point.x(), point.y() + scroll_offset)
                if not hasattr(self, '_masonry_index_map') or self._masonry_index_map is None:
                    self._rebuild_masonry_index_map()
                for global_idx, item in self._masonry_index_map.items():
                    item_rect = QRect(item['x'], item['y'], item['width'], item['height'])
                    if item_rect.contains(adjusted_point):
                        hit_global = int(global_idx)
                        break

            if hit_global >= 0:
                # Map global index → source row → source index → proxy index.
                if hasattr(source_model, 'get_loaded_row_for_global_index'):
                    row = source_model.get_loaded_row_for_global_index(hit_global)
                else:
                    row = hit_global
                if row != -1:
                    src_index = source_model.index(row, 0)
                    if not src_index.isValid():
                        return QModelIndex()
                    proxy_index = self.model().mapFromSource(src_index) if hasattr(self.model(), 'mapFromSource') else src_index
                    if proxy_index.isValid():
                        return proxy_index
                    return QModelIndex()

            return QModelIndex()
        else:
            return super().indexAt(point)
