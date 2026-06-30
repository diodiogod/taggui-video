"""Visual editor and execution dock for named automation pipelines."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from controllers.pipeline_runner import PipelineRunner
from auto_captioning.models_list import MODELS
from utils.pipeline import (
    PIPELINE_STEP_TYPES,
    PipelineDefinition,
    PipelineStep,
    PipelineStore,
    PipelineValidationError,
    default_pipeline,
    new_pipeline_id,
)
from utils.settings import DEFAULT_SETTINGS, settings
from utils.icons import create_chain_link_icon
from utils.marking_model_security import (
    configure_ultralytics_marking_runtime,
    infer_marking_model_task,
    list_marking_model_paths,
    passive_model_warning_text,
    prompt_resolve_runtime_path,
    resolve_marking_model_value,
)


STEP_META = {
    "auto_mark": {
        "title": "Auto Marking",
        "eyebrow": "DETECT",
        "accent": "#27D8C5",
        "description": "Run one detection model across the current scope.",
    },
    "build_ideogram_regions": {
        "title": "Build Ideogram Regions",
        "eyebrow": "STRUCTURE",
        "accent": "#F2B84B",
        "description": "Convert exact-new markings into structured object regions.",
    },
    "auto_caption": {
        "title": "Auto Caption",
        "eyebrow": "ENRICH",
        "accent": "#65A7FF",
        "description": "Generate prose or enrich the Ideogram JSON caption.",
    },
    "save": {
        "title": "Synchronize Search Indexes",
        "eyebrow": "INDEX",
        "accent": "#7ED68A",
        "description": "Refresh searchable database data without rewriting sidecars.",
    },
}


class CompressiblePipelineRoot(QWidget):
    """Keep a normal preferred size while allowing dock layouts to clip it."""

    def minimumSizeHint(self):
        return QSize(0, 0)


class PipelineLinkOverlay(QWidget):
    """Mouse-transparent layer that keeps live connectors above step cards."""

    def __init__(self, step_list):
        super().__init__(step_list.viewport())
        self.step_list = step_list
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.step_list.paint_link_drag(painter, self)


class PipelineGroupConnector(QWidget):
    """Clickable connector drawn from one linked chain control to the next."""

    unlink_requested = Signal(str, str)

    def __init__(self, source_id: str, target_id: str, parent=None):
        super().__init__(parent)
        self.source_id = str(source_id)
        self.target_id = str(target_id)
        self._path = QPainterPath()
        self._hit_path = QPainterPath()
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_endpoints(self, start: QPoint, end: QPoint):
        bounds = QRect(start, end).normalized().adjusted(-10, -10, 11, 11)
        self.setGeometry(bounds)
        local_start = start - bounds.topLeft()
        local_end = end - bounds.topLeft()
        middle_y = (local_start.y() + local_end.y()) / 2.0
        self._path = QPainterPath(local_start)
        self._path.cubicTo(
            local_start.x(),
            middle_y,
            local_end.x(),
            middle_y,
            local_end.x(),
            local_end.y(),
        )
        stroker = QPainterPathStroker()
        stroker.setWidth(14.0)
        self._hit_path = stroker.createStroke(self._path)
        self.setMask(QRegion(self._hit_path.toFillPolygon().toPolygon()))
        self.update()

    def contains_viewport_point(self, viewport_pos: QPoint) -> bool:
        local_pos = viewport_pos - self.geometry().topLeft()
        return self._hit_path.contains(local_pos)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(
            QColor(4, 10, 12, 205),
            7.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(self._path)
        painter.setPen(QPen(
            QColor("#27D8C5"),
            2.2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(self._path)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            QToolTip.hideText()
            self.unlink_requested.emit(self.source_id, self.target_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PipelineStepList(QListWidget):
    """Reorderable card list with a painted execution spine."""

    order_changed = Signal()
    unlink_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipelineStepList")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setSpacing(10)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(0, 8, 8, 8)
        self._active_row = -1
        self._link_drag_source_id: str | None = None
        self._link_drag_pos: QPoint | None = None
        self._link_drag_target_id: str | None = None
        self._link_drag_fixed_id: str | None = None
        self._group_connectors: dict[tuple[str, str], PipelineGroupConnector] = {}
        self._connector_refresh_pending = False
        self._connector_stabilize_pending = False
        self._hide_connectors_until_stable = False
        self.link_overlay = PipelineLinkOverlay(self)
        self.link_overlay.setGeometry(self.viewport().rect())
        self.min_card_zoom = 60
        self.max_card_zoom = 160
        self.card_zoom_step = 10
        self.card_zoom = max(
            self.min_card_zoom,
            min(
                self.max_card_zoom,
                settings.value(
                    "pipeline_card_zoom",
                    defaultValue=100,
                    type=int,
                ),
            ),
        )
        self.setSpacing(max(4, round(10 * self.card_zoom / 100)))
        self.setToolTip(
            "Scroll to navigate. Hold Ctrl and scroll to resize pipeline steps."
        )
        self.model().rowsMoved.connect(lambda *_args: self.order_changed.emit())
        self.verticalScrollBar().valueChanged.connect(
            lambda _value: self.schedule_link_connector_refresh()
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.link_overlay.setGeometry(self.viewport().rect())
        self.schedule_link_connector_refresh()

    def schedule_link_connector_refresh(
        self,
        stabilize: bool = True,
        hide_until_stable: bool = False,
    ):
        if hide_until_stable:
            self._hide_connectors_until_stable = True
            for connector in self._group_connectors.values():
                connector.hide()
        if stabilize and not self._connector_stabilize_pending:
            self._connector_stabilize_pending = True
            QTimer.singleShot(80, self._stabilize_link_connectors)
        if self._connector_refresh_pending:
            return
        self._connector_refresh_pending = True
        QTimer.singleShot(0, self.refresh_link_connectors)

    def _stabilize_link_connectors(self):
        self._connector_stabilize_pending = False
        self._hide_connectors_until_stable = False
        self.refresh_link_connectors()

    def refresh_link_connectors(self):
        self._connector_refresh_pending = False
        self.doItemsLayout()
        wanted: dict[tuple[str, str], tuple[QPoint, QPoint]] = {}
        for row in range(max(0, self.count() - 1)):
            first_card = self._card_for_item(self.item(row))
            second_card = self._card_for_item(self.item(row + 1))
            if (
                first_card is None
                or second_card is None
                or not first_card.geometry().isValid()
                or not second_card.geometry().isValid()
            ):
                continue
            first_step = getattr(first_card, "step", None)
            second_step = getattr(second_card, "step", None)
            first_group = str(getattr(first_step, "settings", {}).get(
                "merge_group", ""
            ))
            second_group = str(getattr(second_step, "settings", {}).get(
                "merge_group", ""
            ))
            if not first_group or first_group != second_group:
                continue
            source_id = str(getattr(first_step, "id", ""))
            target_id = str(getattr(second_step, "id", ""))
            start = self._link_anchor_for_card(first_card, lower=True)
            end = self._link_anchor_for_card(second_card, lower=False)
            wanted[(source_id, target_id)] = (start, end)

        for key, connector in list(self._group_connectors.items()):
            if key in wanted:
                continue
            QToolTip.hideText()
            connector.deleteLater()
            del self._group_connectors[key]
        for key, endpoints in wanted.items():
            connector = self._group_connectors.get(key)
            if connector is None:
                connector = PipelineGroupConnector(*key, self.viewport())
                connector.unlink_requested.connect(self.unlink_requested)
                self._group_connectors[key] = connector
            connector.set_endpoints(*endpoints)
            connector.setVisible(
                not self._hide_connectors_until_stable
                and (
                    not self._link_drag_source_id
                    or self._link_drag_source_id not in key
                )
            )
            connector.raise_()
        if self.link_overlay.isVisible():
            self.link_overlay.raise_()

    def show_link_overlay(self):
        self.link_overlay.setGeometry(self.viewport().rect())
        for key, connector in self._group_connectors.items():
            if self._link_drag_source_id and self._link_drag_source_id in key:
                connector.hide()
        self.link_overlay.show()
        self.link_overlay.raise_()
        self.link_overlay.update()

    def hide_link_overlay(self):
        self.link_overlay.hide()

    def paint_link_drag(self, painter: QPainter, overlay: QWidget):
        if not self._link_drag_source_id or self._link_drag_pos is None:
            return
        source_card = None
        target_card = None
        for row in range(self.count()):
            card = self._card_for_item(self.item(row))
            step_id = str(getattr(getattr(card, "step", None), "id", ""))
            if step_id == self._link_drag_source_id:
                source_card = card
            if step_id == self._link_drag_target_id:
                target_card = card
        if source_card is None:
            return

        source_row = self._row_for_step_id(self._link_drag_source_id)
        target_row = self._row_for_step_id(self._link_drag_target_id)
        fixed_card = None
        fixed_row = -1
        if self._link_drag_fixed_id:
            fixed_row = self._row_for_step_id(self._link_drag_fixed_id)
            if fixed_row >= 0:
                fixed_card = self._card_for_item(self.item(fixed_row))

        if fixed_card is not None:
            fixed_anchor_lower = fixed_row < source_row
            start = self._overlay_point(
                overlay,
                self._link_anchor_for_card(
                    fixed_card,
                    lower=fixed_anchor_lower,
                ),
            )
        else:
            if target_row >= 0:
                source_anchor_lower = source_row <= target_row
            else:
                source_center = self._link_anchor_for_card(
                    source_card,
                    lower=False,
                ) + QPoint(0, source_card.link_button.height() // 2)
                source_anchor_lower = self._link_drag_pos.y() >= source_center.y()
            start = self._overlay_point(
                overlay,
                self._link_anchor_for_card(
                    source_card,
                    lower=source_anchor_lower,
                ),
            )
        end = self._link_drag_pos
        if target_card is not None:
            target_anchor_lower = source_row > target_row
            end = self._overlay_point(
                overlay,
                self._link_anchor_for_card(
                    target_card,
                    lower=target_anchor_lower,
                )
            )
        path = QPainterPath(start)
        control_dx = max(28.0, abs(end.x() - start.x()) * 0.45)
        path.cubicTo(
            start.x() + control_dx,
            start.y(),
            end.x() - control_dx,
            end.y(),
            end.x(),
            end.y(),
        )
        painter.setPen(QPen(
            QColor(4, 10, 12, 215),
            8.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(path)
        painter.setPen(QPen(
            QColor(39, 216, 197, 105),
            5.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(path)
        painter.setPen(QPen(
            QColor("#55F2E2"),
            2.6,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(path)

    def _row_for_step_id(self, step_id: str | None) -> int:
        if not step_id:
            return -1
        for row in range(self.count()):
            card = self._card_for_item(self.item(row))
            if str(getattr(getattr(card, "step", None), "id", "")) == str(step_id):
                return row
        return -1

    def _link_anchor_for_card(self, card, lower: bool) -> QPoint:
        button = card.link_button
        local = button.rect().bottomLeft() if lower else button.rect().topLeft()
        local += QPoint(button.width() // 2, 1 if lower else -1)
        return button.mapTo(self.viewport(), local)

    def _overlay_point(self, overlay: QWidget, viewport_pos: QPoint) -> QPoint:
        return overlay.mapFrom(self.viewport(), viewport_pos)

    def adjust_card_zoom(self, wheel_delta: int):
        if wheel_delta == 0:
            return
        change = self.card_zoom_step if wheel_delta > 0 else -self.card_zoom_step
        new_zoom = max(
            self.min_card_zoom,
            min(self.max_card_zoom, self.card_zoom + change),
        )
        if new_zoom == self.card_zoom:
            return
        self.card_zoom = new_zoom
        self.setSpacing(max(4, round(10 * new_zoom / 100)))
        for row in range(self.count()):
            item = self.item(row)
            row_widget = self.itemWidget(item)
            card = getattr(row_widget, "card", row_widget)
            if card is None:
                continue
            card.set_density(new_zoom)
            item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
        settings.setValue("pipeline_card_zoom", self.card_zoom)
        self.viewport().update()
        self.schedule_link_connector_refresh()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.adjust_card_zoom(
                event.angleDelta().y() or event.pixelDelta().y()
            )
            event.accept()
            return

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            distance = pixel_delta
        else:
            angle_delta = event.angleDelta().y()
            if not angle_delta:
                event.ignore()
                return
            distance = round((angle_delta / 120.0) * 36)
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() - distance)
        event.accept()

    def set_active_row(self, row: int):
        self._active_row = int(row)
        for item_row in range(self.count()):
            card = self._card_for_item(self.item(item_row))
            if card is not None:
                card.set_run_state(
                    "active" if item_row == self._active_row else "idle"
                )
        self.viewport().update()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.viewport().update()
        self.schedule_link_connector_refresh()

    def _card_for_item(self, item):
        widget = self.itemWidget(item)
        return getattr(widget, "card", widget)

    def paintEvent(self, event):
        super().paintEvent(event)
        centers = []
        accents = []
        for row in range(self.count()):
            item_rect = self.visualItemRect(self.item(row))
            if item_rect.isEmpty() or not self.viewport().rect().intersects(item_rect):
                continue
            centers.append((row, item_rect.center().y()))
            card = self._card_for_item(self.item(row))
            accents.append(QColor(card.accent if card is not None else "#27D8C5"))
        if not centers:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        spine_x = 21
        if len(centers) > 1:
            gradient = QLinearGradient(0, centers[0][1], 0, centers[-1][1])
            gradient.setColorAt(0.0, QColor("#27D8C5"))
            gradient.setColorAt(0.55, QColor("#65A7FF"))
            gradient.setColorAt(1.0, QColor("#F2B84B"))
            painter.setPen(QPen(QColor(39, 216, 197, 42), 9.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(spine_x, centers[0][1], spine_x, centers[-1][1])

        if len(centers) > 1:
            painter.setPen(QPen(gradient, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(spine_x, centers[0][1], spine_x, centers[-1][1])

        for visible_index, (row, center_y) in enumerate(centers):
            color = accents[visible_index]
            active = row == self._active_row
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 55), 7.0))
            painter.setBrush(QColor("#11171D"))
            painter.drawEllipse(QPoint(spine_x, center_y), 10, 10)
            painter.setPen(QPen(color, 2.2 if active else 1.4))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 210 if active else 90))
            painter.drawEllipse(QPoint(spine_x, center_y), 7, 7)
            painter.setPen(QColor("#F5FBFF"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(
                spine_x - 7,
                center_y - 7,
                14,
                14,
                Qt.AlignmentFlag.AlignCenter,
                str(row + 1),
            )

class PipelineDragHandle(QLabel):
    drag_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("::::", parent)
        self._press_pos = QPoint()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and (event.pos() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self.drag_requested.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class PipelineLinkHandle(QToolButton):
    drag_started = Signal(str, object)
    drag_moved = Signal(str, object)
    drag_finished = Signal(str, object)
    clicked_without_drag = Signal(str)

    def __init__(self, step_id: str, parent=None):
        super().__init__(parent)
        self.step_id = str(step_id)
        self._press_pos = QPoint()
        self._dragging = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setToolTip(
            "Hold and drag this chain onto an adjacent Auto-Marking step to "
            "merge overlapping detections with the exact same output label and "
            "marking type. Relabel model classes when needed, for example "
            "eyes{eye}, so linked models use one shared label. Click a linked "
            "chain to unlink."
        )

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip and self._pressed:
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._press_pos = event.pos()
        self._dragging = False
        self._pressed = True
        QToolTip.hideText()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        if (
            not self._dragging
            and (event.pos() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
            self.drag_started.emit(
                self.step_id,
                event.globalPosition().toPoint(),
            )
        if self._dragging:
            QToolTip.hideText()
            self.drag_moved.emit(
                self.step_id,
                event.globalPosition().toPoint(),
            )
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pressed = False
        QToolTip.hideText()
        if self._dragging:
            self.drag_finished.emit(
                self.step_id,
                event.globalPosition().toPoint(),
            )
        else:
            self.clicked_without_drag.emit(self.step_id)
        self._dragging = False
        event.accept()


class PipelineFieldLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PipelineStepRow(QWidget):
    """Reserve a clear gutter for the flow spine beside a step card."""

    def __init__(self, card, parent=None):
        super().__init__(parent)
        self.card = card
        layout = QHBoxLayout(self)
        layout.setContentsMargins(38, 0, 4, 0)
        layout.addWidget(card)


class PipelineStepCard(QFrame):
    changed = Signal()
    delete_requested = Signal(str)
    link_requested = Signal(str)
    link_drag_started = Signal(str, object)
    link_drag_moved = Signal(str, object)
    link_drag_finished = Signal(str, object)
    _model_class_cache: dict[str, tuple[int, list[str]]] = {}

    def __init__(self, step: PipelineStep, marking_models: list[str], caption_models: list[str], parent=None):
        super().__init__(parent)
        self.step = step
        self.meta = STEP_META[step.type]
        self.accent = self.meta["accent"]
        self._expanded = False
        self._density = 100
        self._field_labels: list[QLabel] = []
        self.setObjectName("pipelineStepCard")
        self.setProperty("runState", "idle")
        self.setProperty("mergeLinked", bool(step.settings.get("merge_group")))
        self.setProperty("linkDropTarget", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        self.root_layout = root
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        grip = PipelineDragHandle()
        grip.setObjectName("pipelineDragGrip")
        grip.setToolTip("Drag this card to reorder the pipeline")
        grip.drag_requested.connect(self._start_drag)
        header.addWidget(grip)

        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        eyebrow = QLabel(self.meta["eyebrow"])
        eyebrow.setObjectName("pipelineStepEyebrow")
        eyebrow.setStyleSheet(f"color: {self.accent};")
        title = QLabel(self.meta["title"])
        title.setObjectName("pipelineStepTitle")
        title_column.addWidget(eyebrow)
        title_column.addWidget(title)
        header.addLayout(title_column, 1)

        self.enabled_box = QCheckBox()
        self.enabled_box.setToolTip("Enable this step")
        self.enabled_box.setChecked(step.enabled)
        self.enabled_box.toggled.connect(self._enabled_changed)
        header.addWidget(self.enabled_box)

        self.link_button = PipelineLinkHandle(self.step.id)
        self.link_button.setIcon(create_chain_link_icon(
            "#27D8C5" if step.settings.get("merge_group") else "#AFC0CA"
        ))
        self.link_button.clicked_without_drag.connect(self.link_requested)
        self.link_button.drag_started.connect(self.link_drag_started)
        self.link_button.drag_moved.connect(self.link_drag_moved)
        self.link_button.drag_finished.connect(self.link_drag_finished)
        self.link_button.setVisible(self.step.type == "auto_mark")
        header.addWidget(self.link_button)

        self.expand_button = QToolButton()
        self.expand_button.setText("Edit")
        self.expand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_button.clicked.connect(self._toggle_expanded)
        if self.step.type in {"build_ideogram_regions", "save"}:
            self.expand_button.hide()
        header.addWidget(self.expand_button)

        self.remove_button = QToolButton()
        self.remove_button.setText("X")
        self.remove_button.setToolTip("Remove step")
        self.remove_button.clicked.connect(
            lambda: self.delete_requested.emit(self.step.id)
        )
        header.addWidget(self.remove_button)
        root.addLayout(header)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("pipelineStepSummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.config_widget = QWidget()
        self.config_widget.setObjectName("pipelineStepConfig")
        config_layout = QVBoxLayout(self.config_widget)
        self.config_layout = config_layout
        config_layout.setContentsMargins(0, 6, 0, 0)
        config_layout.setSpacing(8)
        self._build_config(config_layout, marking_models, caption_models)
        self.config_widget.hide()
        root.addWidget(self.config_widget)
        self._update_summary()
        self._apply_style()
        self.setWindowOpacity(1.0 if step.enabled else 0.55)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def _apply_style(self):
        scale = self._density / 100.0
        eyebrow_size = max(7, round(8 * scale))
        title_size = max(9, round(13 * scale))
        summary_size = max(8, round(10 * scale))
        summary_indent = max(8, round(25 * scale))
        control_padding_v = max(2, round(5 * scale))
        control_padding_h = max(4, round(7 * scale))
        control_height = max(16, round(22 * scale))
        self.setStyleSheet(
            f"""
            QFrame#pipelineStepCard {{
                background: #171E26;
                border: 1px solid #303B48;
                border-left: 3px solid {self.accent};
                border-radius: 9px;
            }}
            QFrame#pipelineStepCard[runState="active"] {{
                background: #192630;
                border: 1px solid {self.accent};
                border-left: 3px solid {self.accent};
            }}
            QFrame#pipelineStepCard[mergeLinked="true"] {{
                border-right: 2px solid #27D8C5;
            }}
            QFrame#pipelineStepCard[linkDropTarget="true"] {{
                background: #18302F;
                border: 2px solid #27D8C5;
            }}
            QLabel#pipelineDragGrip {{ color: #718091; font-weight: 800; letter-spacing: -1px; }}
            QLabel#pipelineStepEyebrow {{ font-size: {eyebrow_size}px; font-weight: 800; letter-spacing: 1px; }}
            QLabel#pipelineStepTitle {{ color: #F2F7FA; font-size: {title_size}px; font-weight: 700; }}
            QLabel#pipelineStepSummary {{ color: #95A4B5; font-size: {summary_size}px; padding-left: {summary_indent}px; }}
            QWidget#pipelineStepConfig {{ background: #11171D; border: 1px solid #27313C; border-radius: 6px; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: #0D1318; color: #E8F0F5; border: 1px solid #354252;
                border-radius: 5px; padding: {control_padding_v}px {control_padding_h}px;
                min-height: {control_height}px;
            }}
            QToolButton {{ color: #AAB8C5; background: transparent; border: 0; padding: 4px 6px; }}
            QToolButton:hover {{ color: #FFFFFF; background: #2A3541; border-radius: 4px; }}
            QToolButton:disabled {{ color: #4B5661; background: transparent; }}
            QCheckBox {{ color: #AFC0CC; }}
            """
        )

    def set_density(self, zoom_percent: int):
        self._density = max(60, min(160, int(zoom_percent)))
        scale = self._density / 100.0
        self.root_layout.setContentsMargins(
            max(7, round(12 * scale)),
            max(5, round(10 * scale)),
            max(7, round(12 * scale)),
            max(5, round(10 * scale)),
        )
        self.root_layout.setSpacing(max(4, round(8 * scale)))
        self.config_layout.setSpacing(max(4, round(8 * scale)))
        for label in self._field_labels:
            label.setMinimumWidth(max(60, round(92 * scale)))
            label.setStyleSheet(
                f"color: #9EADBA; font-size: {max(8, round(10 * scale))}px; "
                "border: 0;"
            )
        self._apply_style()
        self._refresh_size_hint()

    def _pipeline_step_list(self):
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, PipelineStepList):
            parent = parent.parentWidget()
        return parent if isinstance(parent, PipelineStepList) else None

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            step_list = self._pipeline_step_list()
            if step_list is not None:
                step_list.adjust_card_zoom(
                    event.angleDelta().y() or event.pixelDelta().y()
                )
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step_list = self._pipeline_step_list()
            if step_list is not None:
                step_list.adjust_card_zoom(
                    event.angleDelta().y() or event.pixelDelta().y()
                )
                event.accept()
                return
        super().wheelEvent(event)

    def set_run_state(self, state: str):
        self.setProperty("runState", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _start_drag(self):
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, PipelineStepList):
            parent = parent.parentWidget()
        if not isinstance(parent, PipelineStepList):
            return
        for row in range(parent.count()):
            item = parent.item(row)
            row_widget = parent.itemWidget(item)
            if getattr(row_widget, "card", row_widget) is self:
                parent.setCurrentItem(item)
                parent.startDrag(Qt.DropAction.MoveAction)
                return

    def _field_row(
        self,
        label_text: str,
        widget: QWidget,
        double_click_handler=None,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        label = PipelineFieldLabel(label_text)
        label.setStyleSheet("color: #9EADBA; font-size: 10px; border: 0;")
        label.setMinimumWidth(92)
        if double_click_handler is not None:
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setToolTip(
                "Double-click to load the selected model's default classes."
            )
            label.double_clicked.connect(double_click_handler)
        self._field_labels.append(label)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return row

    def _build_config(self, layout: QVBoxLayout, marking_models: list[str], caption_models: list[str]):
        if self.step.type == "auto_mark":
            self.model_combo = QComboBox()
            self.model_combo.setEditable(True)
            self.model_combo.addItems(marking_models)
            self.model_combo.setCurrentText(str(self.step.settings.get("model", "")))
            self.marking_type_combo = QComboBox()
            self.marking_type_combo.addItems(["hint", "exclude", "include"])
            self.marking_type_combo.setCurrentText(str(self.step.settings.get("marking_type", "hint")))
            class_names = self.step.settings.get("class_names", "")
            if isinstance(class_names, list):
                class_names = ", ".join(str(name) for name in class_names)
            self.class_names_edit = QLineEdit(str(class_names))
            self.class_names_edit.setPlaceholderText(
                "eye{person eye}, hand, tool{held tool}"
            )
            self.class_names_edit.setToolTip(
                "Comma-separated source classes. Rename generated markings with "
                "source_class{output label}; plain names keep the model label. "
                "Linked models only merge detections with the exact same output "
                "label and marking type, so use mappings such as eyes{eye} to "
                "normalize different model labels."
            )
            self.confidence_spin = QDoubleSpinBox()
            self.confidence_spin.setRange(0.01, 1.0)
            self.confidence_spin.setSingleStep(0.01)
            self.confidence_spin.setValue(float(self.step.settings.get("confidence", 0.25)))
            self.iou_spin = QDoubleSpinBox()
            self.iou_spin.setRange(0.01, 1.0)
            self.iou_spin.setSingleStep(0.01)
            self.iou_spin.setValue(float(self.step.settings.get("iou", 0.7)))
            self.max_detections_spin = QSpinBox()
            self.max_detections_spin.setRange(1, 1000)
            self.max_detections_spin.setValue(int(self.step.settings.get("max_detections", 300)))
            self.merge_threshold_spin = QDoubleSpinBox()
            self.merge_threshold_spin.setRange(0.05, 1.0)
            self.merge_threshold_spin.setSingleStep(0.05)
            self.merge_threshold_spin.setValue(float(
                self.step.settings.get("merge_overlap_threshold", 0.6)
            ))
            for text, widget in (
                ("Model", self.model_combo),
                ("Output", self.marking_type_combo),
                ("Confidence", self.confidence_spin),
                ("IoU", self.iou_spin),
                ("Max detections", self.max_detections_spin),
            ):
                layout.addWidget(self._field_row(text, widget))
            classes_row = self._field_row(
                "Classes / labels",
                self.class_names_edit,
                self._populate_default_classes,
            )
            layout.insertWidget(2, classes_row)
            self.merge_threshold_row = self._field_row(
                "Linked overlap",
                self.merge_threshold_spin,
            )
            self.merge_threshold_row.setToolTip(
                "Overlap score required to merge detections from linked models. "
                "Only exact-matching output labels and marking types are compared; "
                "use Classes / labels to normalize names first."
            )
            layout.addWidget(self.merge_threshold_row)
            self.merge_threshold_row.setVisible(
                bool(self.step.settings.get("merge_group"))
            )
            self.model_combo.currentTextChanged.connect(self._sync_settings)
            self.marking_type_combo.currentTextChanged.connect(self._sync_settings)
            self.class_names_edit.textChanged.connect(self._sync_settings)
            self.confidence_spin.valueChanged.connect(self._sync_settings)
            self.iou_spin.valueChanged.connect(self._sync_settings)
            self.max_detections_spin.valueChanged.connect(self._sync_settings)
            self.merge_threshold_spin.valueChanged.connect(self._sync_settings)
        elif self.step.type == "auto_caption":
            self.model_combo = QComboBox()
            self.model_combo.setEditable(True)
            self.model_combo.addItems(caption_models)
            self.model_combo.setCurrentText(str(self.step.settings.get("model", "")))
            self.output_combo = QComboBox()
            self.output_combo.addItems(["Ideogram 4 JSON", "Plain caption"])
            self.output_combo.setCurrentText(str(self.step.settings.get("output_format", "Ideogram 4 JSON")))
            self.structured_box = QCheckBox("Enforce remote JSON schema")
            self.structured_box.setChecked(bool(self.step.settings.get("remote_structured_output", False)))
            layout.addWidget(self._field_row("Model", self.model_combo))
            layout.addWidget(self._field_row("Output", self.output_combo))
            layout.addWidget(self._field_row("Remote", self.structured_box))
            self.model_combo.currentTextChanged.connect(self._sync_settings)
            self.output_combo.currentTextChanged.connect(self._sync_settings)
            self.structured_box.toggled.connect(self._sync_settings)
        else:
            description = QLabel(self.meta["description"])
            description.setWordWrap(True)
            description.setStyleSheet("color: #A7B5C1; padding: 8px; border: 0;")
            layout.addWidget(description)

    def _selected_marking_model_path(self) -> Path:
        model_value = self.model_combo.currentText().strip()
        if not model_value:
            main_window = self.window()
            auto_markings = getattr(main_window, "auto_markings", None)
            if auto_markings is not None:
                model_value = str(
                    auto_markings.marking_settings_form.model_combo_box.currentText()
                    or ""
                ).strip()
        if not model_value:
            raise ValueError("Select an auto-marking model first.")
        root = settings.value(
            "marking_models_directory_path",
            DEFAULT_SETTINGS["marking_models_directory_path"],
            type=str,
        )
        model_path = resolve_marking_model_value(model_value, root)
        if not model_path.exists():
            raise FileNotFoundError(f"Auto-marking model not found: {model_path}")
        return model_path

    def _populate_default_classes(self):
        current_text = self.class_names_edit.text().strip()
        if current_text:
            reply = QMessageBox.question(
                self,
                "Load model classes",
                "Replace the current class filters and custom labels with the "
                "selected model's default class names?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            model_path = prompt_resolve_runtime_path(
                self._selected_marking_model_path(),
                parent=self,
                purpose="inspect",
            )
            modified_ns = model_path.stat().st_mtime_ns
            cache_key = str(model_path.resolve())
            cached = self._model_class_cache.get(cache_key)
            if cached is not None and cached[0] == modified_ns:
                class_names = cached[1]
            else:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    from ultralytics import YOLO

                    configure_ultralytics_marking_runtime(model_path)
                    model = YOLO(
                        model_path,
                        task=infer_marking_model_task(model_path),
                    )
                    class_names = [
                        str(class_name)
                        for _class_id, class_name in sorted(model.names.items())
                    ]
                finally:
                    QApplication.restoreOverrideCursor()
                self._model_class_cache[cache_key] = (
                    modified_ns,
                    class_names,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Load model classes", str(exc))
            return
        self.class_names_edit.setText(", ".join(class_names))

    def _enabled_changed(self, enabled: bool):
        self.step.enabled = bool(enabled)
        self.setWindowOpacity(1.0 if enabled else 0.55)
        self.changed.emit()

    def _toggle_expanded(self):
        self._expanded = not self._expanded
        self.config_widget.setVisible(self._expanded)
        self.expand_button.setText("Done" if self._expanded else "Edit")
        self.remove_button.setEnabled(not self._expanded)
        self.remove_button.setToolTip(
            "Collapse this step before removing it."
            if self._expanded else "Remove step"
        )
        self._refresh_size_hint()

    def _sync_settings(self, *_args):
        if self.step.type == "auto_mark":
            merge_group = str(self.step.settings.get("merge_group") or "")
            self.step.settings = {
                "model": self.model_combo.currentText().strip(),
                "marking_type": self.marking_type_combo.currentText(),
                "class_names": self.class_names_edit.text().strip(),
                "confidence": self.confidence_spin.value(),
                "iou": self.iou_spin.value(),
                "max_detections": self.max_detections_spin.value(),
                "merge_overlap_threshold": self.merge_threshold_spin.value(),
            }
            if merge_group:
                self.step.settings["merge_group"] = merge_group
        elif self.step.type == "auto_caption":
            self.step.settings = {
                "model": self.model_combo.currentText().strip(),
                "output_format": self.output_combo.currentText(),
                "remote_structured_output": self.structured_box.isChecked(),
            }
        self._update_summary()
        self.changed.emit()

    def _update_summary(self):
        if self.step.type == "auto_mark":
            model = Path(str(self.step.settings.get("model") or "Current model")).name
            output = str(self.step.settings.get("marking_type", "hint"))
            linked = "  /  LINKED" if self.step.settings.get("merge_group") else ""
            warning = ""
            try:
                warning_text = passive_model_warning_text(
                    self._selected_marking_model_path()
                )
                if warning_text:
                    warning = "  /  PT"
            except Exception:
                warning = ""
            self.summary_label.setText(
                f"{model}  /  {output}  /  "
                f"conf {float(self.step.settings.get('confidence', 0.25)):.2f}"
                f"{linked}{warning}"
            )
        elif self.step.type == "auto_caption":
            model = str(self.step.settings.get("model") or "Current caption profile")
            self.summary_label.setText(f"{Path(model).name}  /  {self.step.settings.get('output_format', 'Ideogram 4 JSON')}")
        else:
            self.summary_label.setText(self.meta["description"])

    def refresh_link_state(self):
        linked = bool(self.step.settings.get("merge_group"))
        self.setProperty("mergeLinked", linked)
        self.link_button.setIcon(create_chain_link_icon(
            "#27D8C5" if linked else "#AFC0CA"
        ))
        if hasattr(self, "merge_threshold_row"):
            self.merge_threshold_row.setVisible(linked)
        self._update_summary()
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_size_hint()

    def _refresh_size_hint(self):
        self.adjustSize()
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, PipelineStepList):
            parent = parent.parentWidget()
        if isinstance(parent, PipelineStepList):
            for row in range(parent.count()):
                item = parent.item(row)
                row_widget = parent.itemWidget(item)
                if getattr(row_widget, "card", row_widget) is self:
                    item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
                    break
            parent.schedule_link_connector_refresh()


class PipelineEditor(QDockWidget):
    """Named pipeline editor with connected drag-reorder cards."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("pipeline_editor")
        self.setWindowTitle("Pipelines")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumSize(120, 28)
        self.min_ui_zoom = 60
        self.max_ui_zoom = 160
        self.ui_zoom_step = 10
        self.ui_zoom = max(
            self.min_ui_zoom,
            min(
                self.max_ui_zoom,
                settings.value(
                    "pipeline_ui_zoom",
                    defaultValue=100,
                    type=int,
                ),
            ),
        )
        self.store = PipelineStore()
        self.pipelines: list[PipelineDefinition] = []
        self.current_pipeline: PipelineDefinition | None = None
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_profiles)
        self.runner = PipelineRunner(main_window)

        container = CompressiblePipelineRoot()
        container.setObjectName("pipelineEditorRoot")
        container.setMinimumSize(0, 0)
        container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        root = QVBoxLayout(container)
        self.root_layout = root
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.hero = QFrame()
        self.hero.setObjectName("pipelineHero")
        hero_layout = QVBoxLayout(self.hero)
        self.hero_layout = hero_layout
        hero_layout.setContentsMargins(13, 11, 13, 11)
        hero_layout.setSpacing(5)
        self.hero_title = QLabel("AUTOMATION FLOW")
        self.hero_title.setObjectName("pipelineHeroTitle")
        self.hero_subtitle = QLabel("Build once. Run every stage in order.")
        self.hero_subtitle.setObjectName("pipelineHeroSubtitle")
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_subtitle)
        root.addWidget(self.hero)

        self.profile_widget = QWidget()
        profile_row = QHBoxLayout(self.profile_widget)
        self.profile_layout = profile_row
        profile_row.setContentsMargins(0, 0, 0, 0)
        self.pipeline_combo = QComboBox()
        self.pipeline_combo.setEditable(True)
        self.pipeline_combo.currentIndexChanged.connect(self._pipeline_selected)
        self.pipeline_combo.lineEdit().editingFinished.connect(
            self._combo_name_edited
        )
        profile_row.addWidget(self.pipeline_combo, 1)
        for text, tooltip, handler in (
            ("+", "New pipeline", self._new_pipeline),
            ("Copy", "Duplicate pipeline", self._duplicate_pipeline),
            ("X", "Delete pipeline", self._delete_pipeline),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            profile_row.addWidget(button)
        more_button = QToolButton()
        more_button.setText("...")
        more_button.setToolTip("Import or export pipelines")
        more_button.clicked.connect(self._show_profile_menu)
        profile_row.addWidget(more_button)
        root.addWidget(self.profile_widget)

        self.steps_area = QWidget()
        self.steps_area.setMinimumSize(0, 0)
        steps_layout = QVBoxLayout(self.steps_area)
        self.steps_layout = steps_layout
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(2)

        self.step_list = PipelineStepList()
        self.step_list.setMinimumHeight(0)
        self.step_list.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.step_list.order_changed.connect(self._steps_reordered)
        self.step_list.unlink_requested.connect(self._unlink_step_pair)
        steps_layout.addWidget(self.step_list, 1)

        self.add_step_container = QWidget()
        self.add_step_container.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        add_row = QHBoxLayout(self.add_step_container)
        self.add_step_layout = add_row
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(0)
        self.add_step_button = QPushButton("+ Add step")
        self.add_step_button.setObjectName("pipelineAddStep")
        self.add_step_button.clicked.connect(self._show_add_step_menu)
        add_row.addWidget(self.add_step_button)
        add_row.addStretch(1)
        steps_layout.addWidget(self.add_step_container)
        root.addWidget(self.steps_area, 1)

        self.run_panel = QFrame()
        self.run_panel.setObjectName("pipelineRunPanel")
        self.run_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        run_layout = QVBoxLayout(self.run_panel)
        self.run_layout = run_layout
        run_layout.setContentsMargins(10, 9, 10, 9)
        run_layout.setSpacing(7)
        self.scope_widget = QWidget()
        scope_row = QHBoxLayout(self.scope_widget)
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_label = QLabel("Scope")
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Current image", "Selected images", "Filtered images", "All images"])
        scope_row.addWidget(scope_label)
        scope_row.addWidget(self.scope_combo, 1)
        run_layout.addWidget(self.scope_widget)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("pipelineStatus")
        run_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        run_layout.addWidget(self.progress_bar)
        self._progress_reveal_timer = QTimer(self)
        self._progress_reveal_timer.setSingleShot(True)
        self._progress_reveal_timer.setInterval(180)
        self._progress_reveal_timer.timeout.connect(self._reveal_progress_bar)
        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run pipeline")
        self.run_button.setObjectName("pipelineRunButton")
        self.run_button.clicked.connect(self._run_or_cancel)
        button_row.addWidget(self.run_button, 1)
        self.log_button = QToolButton()
        self.log_button.setText("Log")
        self.log_button.setCheckable(True)
        self.log_button.toggled.connect(self._toggle_log)
        button_row.addWidget(self.log_button)
        run_layout.addLayout(button_row)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(130)
        self.log_edit.hide()
        run_layout.addWidget(self.log_edit)
        root.addWidget(self.run_panel)
        self.setWidget(container)
        self._apply_style()
        self._install_ui_zoom_filters()

        self.runner.running_changed.connect(self._running_changed)
        self.runner.step_started.connect(self._step_started)
        self.runner.progress_changed.connect(self._progress_changed)
        self.runner.log_message.connect(self._append_log)
        self.runner.finished.connect(self._run_finished)
        self._load_profiles()
        self._apply_ui_zoom()
        self._update_compact_visibility()

    def minimumSizeHint(self):
        return QSize(120, 28)

    def _install_ui_zoom_filters(self):
        sections = (
            self.widget(),
            self.hero,
            self.profile_widget,
            self.add_step_container,
            self.run_panel,
        )
        for section in sections:
            section.installEventFilter(self)
            for child in section.findChildren(QWidget):
                child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.adjust_ui_zoom(
                event.angleDelta().y() or event.pixelDelta().y()
            )
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.adjust_ui_zoom(
                event.angleDelta().y() or event.pixelDelta().y()
            )
            event.accept()
            return
        super().wheelEvent(event)

    def adjust_ui_zoom(self, wheel_delta: int):
        if wheel_delta == 0:
            return
        change = self.ui_zoom_step if wheel_delta > 0 else -self.ui_zoom_step
        new_zoom = max(
            self.min_ui_zoom,
            min(self.max_ui_zoom, self.ui_zoom + change),
        )
        if new_zoom == self.ui_zoom:
            return
        self.ui_zoom = new_zoom
        settings.setValue("pipeline_ui_zoom", new_zoom)
        self._apply_ui_zoom()

    def _apply_ui_zoom(self):
        scale = self.ui_zoom / 100.0
        self.root_layout.setContentsMargins(*(
            max(4, round(10 * scale)),
        ) * 4)
        self.root_layout.setSpacing(max(4, round(10 * scale)))
        self.hero_layout.setContentsMargins(
            max(6, round(13 * scale)),
            max(5, round(11 * scale)),
            max(6, round(13 * scale)),
            max(5, round(11 * scale)),
        )
        self.hero_layout.setSpacing(max(2, round(5 * scale)))
        self.profile_layout.setSpacing(max(2, round(6 * scale)))
        self.steps_layout.setSpacing(max(1, round(2 * scale)))
        self._apply_style()
        self._update_compact_visibility()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_visibility()

    def _update_compact_visibility(self):
        scale = self.ui_zoom / 100.0
        effective_height = self.height() / max(0.01, scale)
        self.add_step_container.setVisible(effective_height >= 360)
        self.hero.setVisible(effective_height >= 260)
        self.profile_widget.setVisible(effective_height >= 165)
        self.scope_widget.setVisible(effective_height >= 125)
        self.status_label.setVisible(effective_height >= 205)
        if effective_height < 205:
            self.log_edit.hide()
        else:
            self.log_edit.setVisible(self.log_button.isChecked())
        if effective_height < 145:
            self.progress_bar.hide()
        compact = effective_height < 165
        self.run_layout.setContentsMargins(
            max(3, round((5 if compact else 10) * scale)),
            max(2, round((4 if compact else 9) * scale)),
            max(3, round((5 if compact else 10) * scale)),
            max(2, round((4 if compact else 9) * scale)),
        )
        self.run_layout.setSpacing(
            max(2, round((3 if compact else 7) * scale))
        )

    def _apply_style(self):
        scale = self.ui_zoom / 100.0
        base_style = """
            QWidget#pipelineEditorRoot { background: #0C1116; color: #DDE7ED; }
            QFrame#pipelineHero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #15252A, stop:0.6 #14202A, stop:1 #1D2530); border: 1px solid #2D4650; border-radius: 9px; }
            QLabel#pipelineHeroTitle { color: #62E7D8; font-size: 12px; font-weight: 800; letter-spacing: 2px; }
            QLabel#pipelineHeroSubtitle { color: #93A5B4; font-size: 10px; }
            QListWidget#pipelineStepList { background: #0F151B; border: 1px solid #202A34; border-radius: 9px; outline: 0; }
            QListWidget#pipelineStepList::item { background: transparent; border: 0; }
            QListWidget#pipelineStepList::item:selected { background: transparent; }
            QListWidget#pipelineStepList::drop-indicator { background: #62E7D8; height: 2px; }
            QLineEdit, QComboBox { background: #121920; color: #E7EEF2; border: 1px solid #34414E; border-radius: 6px; padding: 6px 8px; min-height: 24px; }
            QToolButton { color: #AFC0CA; background: #182129; border: 1px solid #303C48; border-radius: 5px; padding: 5px 7px; }
            QToolButton:hover { color: #FFFFFF; border-color: #4A6070; background: #202C36; }
            QPushButton#pipelineAddStep { color: #B8C8D2; background: transparent; border: 1px dashed #3B4A57; border-radius: 7px; padding: 7px 12px; }
            QPushButton#pipelineAddStep:hover { color: #62E7D8; border-color: #42AFA4; background: #122321; }
            QFrame#pipelineRunPanel { background: #121920; border: 1px solid #2B3742; border-radius: 9px; }
            QFrame#pipelineRunPanel QLabel { color: #AFC0CC; }
            QLabel#pipelineStatus { color: #94A5B2; font-size: 10px; }
            QPushButton#pipelineRunButton { color: #071512; background: #62E7D8; border: 0; border-radius: 7px; padding: 8px 12px; font-weight: 800; }
            QPushButton#pipelineRunButton:hover { background: #7CF2E5; }
            QPushButton#pipelineRunButton[active="true"] { color: #FFF4E8; background: #B85C3D; }
            QProgressBar { color: #DDE8EC; background: #0A1015; border: 1px solid #2D3944; border-radius: 5px; text-align: center; min-height: 16px; }
            QProgressBar::chunk { background: #35C7B8; border-radius: 4px; }
            QPlainTextEdit { background: #090E12; color: #9FB7C2; border: 1px solid #26323C; border-radius: 6px; font-family: Consolas; font-size: 9px; }
        """
        scaled_style = f"""
            QLabel#pipelineHeroTitle {{
                font-size: {max(8, round(12 * scale))}px;
                letter-spacing: {max(1, round(2 * scale))}px;
            }}
            QLabel#pipelineHeroSubtitle {{
                font-size: {max(8, round(10 * scale))}px;
            }}
            QLineEdit, QComboBox {{
                font-size: {max(8, round(10 * scale))}px;
                padding: {max(2, round(6 * scale))}px {max(4, round(8 * scale))}px;
                min-height: {max(16, round(24 * scale))}px;
            }}
            QToolButton {{
                font-size: {max(8, round(10 * scale))}px;
                padding: {max(2, round(5 * scale))}px {max(3, round(7 * scale))}px;
            }}
            QPushButton#pipelineAddStep {{
                font-size: {max(8, round(10 * scale))}px;
                padding: {max(3, round(7 * scale))}px {max(5, round(12 * scale))}px;
            }}
            QFrame#pipelineRunPanel QLabel {{
                font-size: {max(8, round(10 * scale))}px;
            }}
            QLabel#pipelineStatus {{
                font-size: {max(8, round(10 * scale))}px;
            }}
            QPushButton#pipelineRunButton {{
                font-size: {max(8, round(10 * scale))}px;
                padding: {max(4, round(8 * scale))}px {max(6, round(12 * scale))}px;
            }}
            QProgressBar {{
                min-height: {max(10, round(16 * scale))}px;
            }}
            QPlainTextEdit {{
                font-size: {max(7, round(9 * scale))}px;
            }}
        """
        self.widget().setStyleSheet(
            base_style + scaled_style
        )

    def _marking_models(self) -> list[str]:
        root = settings.value("marking_models_directory_path", DEFAULT_SETTINGS["marking_models_directory_path"], type=str)
        if not root:
            return []
        base = Path(root)
        return [str(path.relative_to(base)) for path in list_marking_model_paths(base)]

    def refresh_marking_models(self, model_paths: list[str] | None = None):
        """Refresh open Auto-Marking cards without rebuilding their UI state."""
        available_models = (
            list(model_paths) if model_paths is not None else self._marking_models()
        )
        for row in range(self.step_list.count()):
            card = self.step_list._card_for_item(self.step_list.item(row))
            if getattr(getattr(card, "step", None), "type", "") != "auto_mark":
                continue
            combo = getattr(card, "model_combo", None)
            if combo is None:
                continue
            current_text = str(combo.currentText() or "")
            blocked = combo.blockSignals(True)
            combo.clear()
            combo.addItems(available_models)
            combo.setCurrentText(current_text)
            combo.blockSignals(blocked)

    def _caption_models(self) -> list[str]:
        values = []
        form = getattr(self.main_window.auto_captioner, "caption_settings_form", None)
        combo = getattr(form, "model_combo_box", None)
        if combo is not None:
            values.extend(combo.itemText(i) for i in range(combo.count()))
        for model in MODELS:
            if model not in values:
                values.append(model)
        return values

    def _load_profiles(self):
        try:
            self.pipelines = self.store.load()
        except PipelineValidationError as exc:
            QMessageBox.warning(self, "Pipeline profiles", str(exc))
            self.pipelines = []
        if not self.pipelines:
            self.pipelines = [default_pipeline()]
            self.store.save(self.pipelines)
        self._refresh_pipeline_combo(0)

    def _refresh_pipeline_combo(self, selected_index: int):
        self._loading = True
        self.pipeline_combo.clear()
        self.pipeline_combo.addItems([pipeline.name for pipeline in self.pipelines])
        self.pipeline_combo.setCurrentIndex(max(0, min(selected_index, len(self.pipelines) - 1)))
        self._loading = False
        self._pipeline_selected(self.pipeline_combo.currentIndex())

    def _pipeline_selected(self, index: int):
        if self._loading or index < 0 or index >= len(self.pipelines):
            return
        self.current_pipeline = self.pipelines[index]
        self._rebuild_steps()

    def _rebuild_steps(self):
        self.step_list.clear()
        if self.current_pipeline is None:
            return
        marking_models = self._marking_models()
        caption_models = self._caption_models()
        for step in self.current_pipeline.steps:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, step.id)
            card = PipelineStepCard(step, marking_models, caption_models, self.step_list)
            card.set_density(self.step_list.card_zoom)
            card.changed.connect(
                lambda step_id=step.id: self._step_card_changed(step_id)
            )
            card.delete_requested.connect(self._delete_step)
            card.link_requested.connect(self._toggle_step_link)
            card.link_drag_started.connect(self._begin_step_link_drag)
            card.link_drag_moved.connect(self._update_step_link_drag)
            card.link_drag_finished.connect(self._finish_step_link_drag)
            row_widget = PipelineStepRow(card, self.step_list)
            item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
            self.step_list.addItem(item)
            self.step_list.setItemWidget(item, row_widget)
        self.step_list.schedule_link_connector_refresh()

    def _step_card(self, step_id: str):
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) != str(step_id):
                continue
            row_widget = self.step_list.itemWidget(item)
            return getattr(row_widget, "card", row_widget)
        return None

    def _step_card_changed(self, step_id: str):
        if self.current_pipeline is None:
            return
        source = next(
            (step for step in self.current_pipeline.steps if step.id == step_id),
            None,
        )
        if source is not None:
            group_id = str(source.settings.get("merge_group") or "")
            if group_id:
                threshold = float(
                    source.settings.get("merge_overlap_threshold", 0.6)
                )
                for step in self.current_pipeline.steps:
                    if (
                        step is source
                        or str(step.settings.get("merge_group") or "") != group_id
                    ):
                        continue
                    step.settings["merge_overlap_threshold"] = threshold
                    card = self._step_card(step.id)
                    spin = getattr(card, "merge_threshold_spin", None)
                    if spin is not None and spin.value() != threshold:
                        blocked = spin.blockSignals(True)
                        spin.setValue(threshold)
                        spin.blockSignals(blocked)
        self._schedule_save()

    def _toggle_step_link(self, step_id: str):
        if self.current_pipeline is None:
            return
        steps = self.current_pipeline.steps
        row = next((i for i, step in enumerate(steps) if step.id == step_id), -1)
        if row < 0 or steps[row].type != "auto_mark":
            return
        step = steps[row]
        if step.settings.get("merge_group"):
            step.settings.pop("merge_group", None)
            self._normalize_merge_groups()
            self._refresh_merge_link_ui()
            self._schedule_save()
            return
        self.status_label.setText(
            "Drag onto an adjacent Auto-Marking card. Linked detections require "
            "matching output labels and marking types."
        )

    def _unlink_step_pair(self, source_id: str, target_id: str):
        if self.current_pipeline is None:
            return
        steps = self.current_pipeline.steps
        source_row = next(
            (index for index, step in enumerate(steps) if step.id == source_id),
            -1,
        )
        target_row = next(
            (index for index, step in enumerate(steps) if step.id == target_id),
            -1,
        )
        if abs(source_row - target_row) != 1:
            return
        group_id = str(steps[source_row].settings.get("merge_group") or "")
        if not group_id or str(
            steps[target_row].settings.get("merge_group") or ""
        ) != group_id:
            return

        boundary = min(source_row, target_row)
        positions = [
            index
            for index, step in enumerate(steps)
            if str(step.settings.get("merge_group") or "") == group_id
        ]
        segments = (
            [position for position in positions if position <= boundary],
            [position for position in positions if position > boundary],
        )
        first_group_assigned = False
        for segment in segments:
            if len(segment) < 2:
                for position in segment:
                    steps[position].settings.pop("merge_group", None)
                continue
            segment_group = (
                group_id if not first_group_assigned else new_pipeline_id("merge")
            )
            first_group_assigned = True
            for position in segment:
                steps[position].settings["merge_group"] = segment_group
        self._refresh_merge_link_ui()
        self._schedule_save()

    def _refresh_merge_link_ui(self):
        """Apply merge changes without destroying and recreating step cards."""
        for row in range(self.step_list.count()):
            card = self.step_list._card_for_item(self.step_list.item(row))
            if card is not None:
                card.refresh_link_state()
                card.updateGeometry()
        self.step_list.doItemsLayout()
        self.step_list.viewport().update()
        self.step_list.schedule_link_connector_refresh(hide_until_stable=True)

    def _merge_group_member_positions(self, row: int) -> set[int]:
        if self.current_pipeline is None or not 0 <= row < len(self.current_pipeline.steps):
            return set()
        step = self.current_pipeline.steps[row]
        group_id = str(step.settings.get("merge_group") or "")
        if not group_id:
            return {row}
        return {
            index
            for index, candidate in enumerate(self.current_pipeline.steps)
            if str(candidate.settings.get("merge_group") or "") == group_id
        }

    def _can_link_steps(self, source_id: str, target_id: str) -> bool:
        if self.current_pipeline is None or source_id == target_id:
            return False
        steps = self.current_pipeline.steps
        source_row = next(
            (index for index, step in enumerate(steps) if step.id == source_id),
            -1,
        )
        target_row = next(
            (index for index, step in enumerate(steps) if step.id == target_id),
            -1,
        )
        if source_row < 0 or target_row < 0:
            return False
        if steps[source_row].type != "auto_mark" or steps[target_row].type != "auto_mark":
            return False
        source_group = self._merge_group_member_positions(source_row)
        target_group = self._merge_group_member_positions(target_row)
        if source_group == target_group:
            return False
        combined = source_group | target_group
        return combined == set(range(min(combined), max(combined) + 1))

    def _step_id_at_global_pos(self, global_pos: QPoint):
        viewport_pos = self.step_list.viewport().mapFromGlobal(global_pos)
        item = self.step_list.itemAt(viewport_pos)
        if item is None:
            return None
        card = self.step_list._card_for_item(item)
        return str(getattr(getattr(card, "step", None), "id", "")) or None

    def _existing_link_contains_global_pos(
        self,
        source_id: str | None,
        fixed_id: str | None,
        global_pos: QPoint,
    ) -> bool:
        if not source_id or not fixed_id:
            return False
        viewport_pos = self.step_list.viewport().mapFromGlobal(global_pos)
        keys = ((str(source_id), str(fixed_id)), (str(fixed_id), str(source_id)))
        for key in keys:
            connector = self.step_list._group_connectors.get(key)
            if (
                connector is not None
                and connector.contains_viewport_point(viewport_pos)
            ):
                return True
        return False

    def _link_target_at_global_pos(self, source_id: str, global_pos: QPoint):
        target_id = self._step_id_at_global_pos(global_pos)
        if target_id is None:
            return None
        return target_id if self._can_link_steps(source_id, target_id) else None

    def _set_link_drop_target(self, target_id: str | None):
        for row in range(self.step_list.count()):
            card = self.step_list._card_for_item(self.step_list.item(row))
            is_target = str(card.step.id) == str(target_id or "")
            if bool(card.property("linkDropTarget")) == is_target:
                continue
            card.setProperty("linkDropTarget", is_target)
            card.style().unpolish(card)
            card.style().polish(card)

    def _begin_step_link_drag(self, step_id: str, global_pos: QPoint):
        QToolTip.hideText()
        self.step_list._link_drag_source_id = str(step_id)
        self.step_list._link_drag_pos = self.step_list.viewport().mapFromGlobal(
            global_pos
        )
        self.step_list._link_drag_target_id = None
        self.step_list._link_drag_fixed_id = self._linked_drag_fixed_neighbor(
            step_id
        )
        self.step_list.show_link_overlay()
        self._update_step_link_drag(step_id, global_pos)

    def _update_step_link_drag(self, step_id: str, global_pos: QPoint):
        if self.step_list._link_drag_source_id != str(step_id):
            return
        QToolTip.hideText()
        target_id = self._link_target_at_global_pos(step_id, global_pos)
        self.step_list._link_drag_pos = self.step_list.viewport().mapFromGlobal(
            global_pos
        )
        self.step_list._link_drag_target_id = target_id
        self._set_link_drop_target(target_id)
        self.step_list.viewport().update()
        self.step_list.link_overlay.raise_()
        self.step_list.link_overlay.update()

    def _finish_step_link_drag(self, step_id: str, global_pos: QPoint):
        self._update_step_link_drag(step_id, global_pos)
        target_id = self.step_list._link_drag_target_id
        dropped_step_id = self._step_id_at_global_pos(global_pos)
        fixed_id = self.step_list._link_drag_fixed_id
        dropped_on_existing_link = self._existing_link_contains_global_pos(
            step_id,
            fixed_id,
            global_pos,
        )
        source = None
        if self.current_pipeline is not None:
            source = next(
                (step for step in self.current_pipeline.steps if step.id == step_id),
                None,
            )
        source_was_linked = bool(
            source is not None and source.settings.get("merge_group")
        )
        self.step_list._link_drag_source_id = None
        self.step_list._link_drag_pos = None
        self.step_list._link_drag_target_id = None
        self.step_list._link_drag_fixed_id = None
        self._set_link_drop_target(None)
        self.step_list.hide_link_overlay()
        self.step_list.viewport().update()
        if target_id:
            self._link_steps(step_id, target_id)
        elif (
            source_was_linked
            and dropped_step_id != fixed_id
            and not dropped_on_existing_link
        ):
            self._toggle_step_link(step_id)
            self.status_label.setText("Step detached from its merge group.")
        elif source_was_linked:
            self.status_label.setText("Step link kept.")
        else:
            self.status_label.setText(
                "Drop the chain on an adjacent Auto-Marking card."
            )
        self.step_list.schedule_link_connector_refresh()

    def _linked_drag_fixed_neighbor(self, step_id: str):
        if self.current_pipeline is None:
            return None
        steps = self.current_pipeline.steps
        row = next((index for index, step in enumerate(steps) if step.id == step_id), -1)
        if row < 0:
            return None
        group_id = str(steps[row].settings.get("merge_group") or "")
        if not group_id:
            return None
        previous_step = steps[row - 1] if row > 0 else None
        next_step = steps[row + 1] if row + 1 < len(steps) else None
        if (
            previous_step is not None
            and str(previous_step.settings.get("merge_group") or "") == group_id
        ):
            return previous_step.id
        if (
            next_step is not None
            and str(next_step.settings.get("merge_group") or "") == group_id
        ):
            return next_step.id
        return None

    def _link_steps(self, source_id: str, target_id: str):
        if self.current_pipeline is None or not self._can_link_steps(source_id, target_id):
            return
        steps = self.current_pipeline.steps
        source_row = next(index for index, step in enumerate(steps) if step.id == source_id)
        target_row = next(index for index, step in enumerate(steps) if step.id == target_id)
        member_positions = (
            self._merge_group_member_positions(source_row)
            | self._merge_group_member_positions(target_row)
        )
        source = steps[source_row]
        target = steps[target_row]
        group_id = str(
            target.settings.get("merge_group")
            or source.settings.get("merge_group")
            or new_pipeline_id("merge")
        )
        threshold = float(
            target.settings.get(
                "merge_overlap_threshold",
                source.settings.get("merge_overlap_threshold", 0.6),
            )
        )
        for position in member_positions:
            steps[position].settings["merge_group"] = group_id
            steps[position].settings["merge_overlap_threshold"] = threshold
        self._refresh_merge_link_ui()
        self._schedule_save()

    def _normalize_merge_groups(self):
        if self.current_pipeline is None:
            return
        steps = self.current_pipeline.steps
        group_positions: dict[str, list[int]] = {}
        for index, step in enumerate(steps):
            group_id = str(step.settings.get("merge_group") or "")
            if group_id:
                group_positions.setdefault(group_id, []).append(index)
        for group_id, positions in group_positions.items():
            runs = []
            current_run = []
            for position in positions:
                if current_run and position != current_run[-1] + 1:
                    runs.append(current_run)
                    current_run = []
                current_run.append(position)
            if current_run:
                runs.append(current_run)
            kept_run = False
            for run in runs:
                if len(run) < 2:
                    steps[run[0]].settings.pop("merge_group", None)
                    continue
                run_group = group_id if not kept_run else new_pipeline_id("merge")
                kept_run = True
                for position in run:
                    steps[position].settings["merge_group"] = run_group

    def _combo_name_edited(self):
        if self._loading or self.current_pipeline is None:
            return
        cleaned = self.pipeline_combo.currentText().strip()
        if not cleaned:
            self.pipeline_combo.setCurrentText(self.current_pipeline.name)
            return
        self.current_pipeline.name = cleaned
        index = self.pipelines.index(self.current_pipeline)
        self._loading = True
        self.pipeline_combo.setItemText(index, cleaned)
        self.pipeline_combo.setCurrentIndex(index)
        self._loading = False
        self._schedule_save()

    def _new_pipeline(self):
        pipeline = PipelineDefinition(name=f"Pipeline {len(self.pipelines) + 1}")
        self.pipelines.append(pipeline)
        self._refresh_pipeline_combo(len(self.pipelines) - 1)
        self._schedule_save()

    def _duplicate_pipeline(self):
        if self.current_pipeline is None:
            return
        pipeline = PipelineDefinition.from_dict(self.current_pipeline.to_dict())
        pipeline.id = new_pipeline_id()
        pipeline.name = f"{pipeline.name} copy"
        for step in pipeline.steps:
            step.id = new_pipeline_id("step")
        self.pipelines.append(pipeline)
        self._refresh_pipeline_combo(len(self.pipelines) - 1)
        self._schedule_save()

    def _delete_pipeline(self):
        if self.current_pipeline is None or len(self.pipelines) <= 1:
            return
        index = self.pipelines.index(self.current_pipeline)
        self.pipelines.pop(index)
        self._refresh_pipeline_combo(max(0, index - 1))
        self._schedule_save()

    def _show_profile_menu(self):
        menu = QMenu(self)
        import_action = menu.addAction("Import pipeline...")
        export_action = menu.addAction("Export current pipeline...")
        chosen = menu.exec(self.sender().mapToGlobal(QPoint(0, self.sender().height())))
        if chosen is import_action:
            self._import_pipeline()
        elif chosen is export_action:
            self._export_pipeline()

    def _import_pipeline(self):
        path_text, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import pipeline",
            "",
            "Pipeline JSON (*.json)",
        )
        if not path_text:
            return
        try:
            import json
            payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
            pipeline = PipelineDefinition.from_dict(payload)
            pipeline.id = new_pipeline_id()
            for step in pipeline.steps:
                step.id = new_pipeline_id("step")
        except (OSError, UnicodeError, ValueError, PipelineValidationError) as exc:
            QMessageBox.warning(self, "Import pipeline", str(exc))
            return
        self.pipelines.append(pipeline)
        self._refresh_pipeline_combo(len(self.pipelines) - 1)
        self._schedule_save()

    def _export_pipeline(self):
        if self.current_pipeline is None:
            return
        suggested = self.current_pipeline.name.strip().replace(" ", "_") or "pipeline"
        path_text, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export pipeline",
            f"{suggested}.json",
            "Pipeline JSON (*.json)",
        )
        if not path_text:
            return
        path = Path(path_text)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            import json
            path.write_text(
                json.dumps(self.current_pipeline.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Export pipeline", str(exc))

    def _show_add_step_menu(self):
        menu = QMenu(self)
        for step_type in PIPELINE_STEP_TYPES:
            meta = STEP_META[step_type]
            action = menu.addAction(f"{meta['eyebrow'].title()}  -  {meta['title']}")
            action.triggered.connect(lambda _checked=False, value=step_type: self._add_step(value))
        menu.exec(self.add_step_button.mapToGlobal(QPoint(0, self.add_step_button.height())))

    def _add_step(self, step_type: str):
        if self.current_pipeline is None:
            return
        settings_payload = {"output_format": "Ideogram 4 JSON"} if step_type == "auto_caption" else {}
        self.current_pipeline.steps.append(PipelineStep(step_type, settings_payload))
        self._rebuild_steps()
        self.step_list.scrollToBottom()
        self._schedule_save()

    def _delete_step(self, step_id: str):
        if self.current_pipeline is None:
            return
        self.current_pipeline.steps = [step for step in self.current_pipeline.steps if step.id != step_id]
        self._normalize_merge_groups()
        self._rebuild_steps()
        self._schedule_save()

    def _steps_reordered(self):
        if self.current_pipeline is None:
            return
        by_id = {step.id: step for step in self.current_pipeline.steps}
        ordered = []
        for row in range(self.step_list.count()):
            step_id = str(self.step_list.item(row).data(Qt.ItemDataRole.UserRole))
            if step_id in by_id:
                ordered.append(by_id[step_id])
        self.current_pipeline.steps = ordered
        self._normalize_merge_groups()
        self._rebuild_steps()
        self._schedule_save()

    def _schedule_save(self):
        if not self._loading:
            self._save_timer.start()

    def _save_profiles(self):
        try:
            self.store.save(self.pipelines)
        except (OSError, PipelineValidationError) as exc:
            self.status_label.setText(f"Save failed: {exc}")

    def _active_browser_models(self):
        manager = getattr(self.main_window, "_context_switch_manager", None)
        secondary = getattr(self.main_window, "_secondary_browser", None)
        if (
            manager is not None
            and getattr(manager, "active_context", "primary") == "secondary"
            and secondary is not None
            and not secondary.dock.isHidden()
        ):
            return (
                secondary.image_list_model,
                secondary.proxy_image_list_model,
                secondary.dock,
            )
        return (
            self.main_window.image_list_model,
            self.main_window.proxy_image_list_model,
            self.main_window.image_list,
        )

    def _scope_indices(self) -> tuple[object, list[QModelIndex]]:
        scope = self.scope_combo.currentText()
        source_model, proxy_model, image_list = self._active_browser_models()
        if scope == "Current image":
            current = image_list.list_view.currentIndex()
            indices = [proxy_model.mapToSource(current)] if current.isValid() else []
            return source_model, indices
        if scope == "Selected images":
            return source_model, image_list.get_selected_image_indices()
        if scope == "Filtered images":
            indices = []
            for row in range(proxy_model.rowCount()):
                proxy_index = proxy_model.index(row, 0)
                if proxy_index.data(Qt.ItemDataRole.UserRole) is not None:
                    indices.append(proxy_model.mapToSource(proxy_index))
            return source_model, indices
        return source_model, [
            source_model.index(row, 0)
            for row in range(source_model.rowCount())
        ]

    def _run_or_cancel(self):
        if self.runner.is_running:
            self.runner.cancel()
            return
        if self.current_pipeline is None:
            return
        self._save_profiles()
        self.log_edit.clear()
        try:
            source_model, image_indices = self._scope_indices()
            self.runner.run_pipeline(
                self.current_pipeline,
                image_indices,
                source_model,
            )
        except PipelineValidationError as exc:
            self.status_label.setText(str(exc))

    def _running_changed(self, running: bool):
        self.run_button.setText("Cancel pipeline" if running else "Run pipeline")
        self.run_button.setProperty("active", running)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self.pipeline_combo.setEnabled(not running)
        self.add_step_button.setEnabled(not running)
        self.scope_combo.setEnabled(not running)
        if not running:
            self.step_list.set_active_row(-1)
        self._update_compact_visibility()

    def _step_started(self, current: int, total: int, title: str):
        active_row = -1
        if 0 < current <= len(self.runner.steps):
            active_id = self.runner.steps[current - 1].id
            for row in range(self.step_list.count()):
                if self.step_list.item(row).data(Qt.ItemDataRole.UserRole) == active_id:
                    active_row = row
                    break
        self.step_list.set_active_row(active_row)
        self.status_label.setText(f"Step {current}/{total}: {title}")
        self.progress_bar.setRange(0, max(1, len(self.runner.image_indices)))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
        self.progress_bar.hide()
        self._progress_reveal_timer.start()
        self._update_compact_visibility()

    def _progress_changed(self, value: int, total: int, title: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat("%v / %m")
        if total > 1 and not self.progress_bar.isVisible() and not self._progress_reveal_timer.isActive():
            self._reveal_progress_bar()

    def _append_log(self, message: str):
        text = str(message or "").strip()
        if text:
            self.log_edit.appendPlainText(text)

    def _run_finished(self, success: bool, message: str):
        self.status_label.setText(message)
        self._progress_reveal_timer.stop()
        self.progress_bar.hide()
        self._update_compact_visibility()

    def _toggle_log(self, visible: bool):
        self.log_edit.setVisible(visible and self.height() >= 205)

    def _reveal_progress_bar(self):
        if not self.runner.is_running:
            return
        if self.height() < 145:
            return
        self.progress_bar.show()
