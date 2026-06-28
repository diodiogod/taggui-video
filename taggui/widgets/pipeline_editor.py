"""Visual editor and execution dock for named automation pipelines."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPen
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
        "title": "Save Metadata",
        "eyebrow": "COMMIT",
        "accent": "#7ED68A",
        "description": "Flush captions, markings, and searchable indexes.",
    },
}


class PipelineStepList(QListWidget):
    """Reorderable card list with a painted execution spine."""

    order_changed = Signal()

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
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(0, 8, 8, 8)
        self._active_row = -1
        self.model().rowsMoved.connect(lambda *_args: self.order_changed.emit())

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

    def __init__(self, step: PipelineStep, marking_models: list[str], caption_models: list[str], parent=None):
        super().__init__(parent)
        self.step = step
        self.meta = STEP_META[step.type]
        self.accent = self.meta["accent"]
        self._expanded = False
        self.setObjectName("pipelineStepCard")
        self.setProperty("runState", "idle")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
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

        self.expand_button = QToolButton()
        self.expand_button.setText("Edit")
        self.expand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_button.clicked.connect(self._toggle_expanded)
        if self.step.type in {"build_ideogram_regions", "save"}:
            self.expand_button.hide()
        header.addWidget(self.expand_button)

        remove_button = QToolButton()
        remove_button.setText("X")
        remove_button.setToolTip("Remove step")
        remove_button.clicked.connect(lambda: self.delete_requested.emit(self.step.id))
        header.addWidget(remove_button)
        root.addLayout(header)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("pipelineStepSummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.config_widget = QWidget()
        self.config_widget.setObjectName("pipelineStepConfig")
        config_layout = QVBoxLayout(self.config_widget)
        config_layout.setContentsMargins(0, 6, 0, 0)
        config_layout.setSpacing(8)
        self._build_config(config_layout, marking_models, caption_models)
        self.config_widget.hide()
        root.addWidget(self.config_widget)
        self._update_summary()
        self._apply_style()
        self.setWindowOpacity(1.0 if step.enabled else 0.55)

    def _apply_style(self):
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
            QLabel#pipelineDragGrip {{ color: #718091; font-weight: 800; letter-spacing: -1px; }}
            QLabel#pipelineStepEyebrow {{ font-size: 8px; font-weight: 800; letter-spacing: 1px; }}
            QLabel#pipelineStepTitle {{ color: #F2F7FA; font-size: 13px; font-weight: 700; }}
            QLabel#pipelineStepSummary {{ color: #95A4B5; font-size: 10px; padding-left: 25px; }}
            QWidget#pipelineStepConfig {{ background: #11171D; border: 1px solid #27313C; border-radius: 6px; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: #0D1318; color: #E8F0F5; border: 1px solid #354252;
                border-radius: 5px; padding: 5px 7px; min-height: 22px;
            }}
            QToolButton {{ color: #AAB8C5; background: transparent; border: 0; padding: 4px 6px; }}
            QToolButton:hover {{ color: #FFFFFF; background: #2A3541; border-radius: 4px; }}
            QCheckBox {{ color: #AFC0CC; }}
            """
        )

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

    def _field_row(self, label_text: str, widget: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        label = QLabel(label_text)
        label.setStyleSheet("color: #9EADBA; font-size: 10px; border: 0;")
        label.setMinimumWidth(92)
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
            self.class_names_edit.setPlaceholderText("Optional class names, comma separated")
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
            for text, widget in (
                ("Model", self.model_combo),
                ("Output", self.marking_type_combo),
                ("Classes", self.class_names_edit),
                ("Confidence", self.confidence_spin),
                ("IoU", self.iou_spin),
                ("Max detections", self.max_detections_spin),
            ):
                layout.addWidget(self._field_row(text, widget))
            self.model_combo.currentTextChanged.connect(self._sync_settings)
            self.marking_type_combo.currentTextChanged.connect(self._sync_settings)
            self.class_names_edit.textChanged.connect(self._sync_settings)
            self.confidence_spin.valueChanged.connect(self._sync_settings)
            self.iou_spin.valueChanged.connect(self._sync_settings)
            self.max_detections_spin.valueChanged.connect(self._sync_settings)
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

    def _enabled_changed(self, enabled: bool):
        self.step.enabled = bool(enabled)
        self.setWindowOpacity(1.0 if enabled else 0.55)
        self.changed.emit()

    def _toggle_expanded(self):
        self._expanded = not self._expanded
        self.config_widget.setVisible(self._expanded)
        self.expand_button.setText("Done" if self._expanded else "Edit")
        self._refresh_size_hint()

    def _sync_settings(self, *_args):
        if self.step.type == "auto_mark":
            self.step.settings = {
                "model": self.model_combo.currentText().strip(),
                "marking_type": self.marking_type_combo.currentText(),
                "class_names": self.class_names_edit.text().strip(),
                "confidence": self.confidence_spin.value(),
                "iou": self.iou_spin.value(),
                "max_detections": self.max_detections_spin.value(),
            }
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
            self.summary_label.setText(f"{model}  /  {output}  /  conf {float(self.step.settings.get('confidence', 0.25)):.2f}")
        elif self.step.type == "auto_caption":
            model = str(self.step.settings.get("model") or "Current caption profile")
            self.summary_label.setText(f"{Path(model).name}  /  {self.step.settings.get('output_format', 'Ideogram 4 JSON')}")
        else:
            self.summary_label.setText(self.meta["description"])

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


class PipelineEditor(QDockWidget):
    """Named pipeline editor with connected drag-reorder cards."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("pipeline_editor")
        self.setWindowTitle("Pipelines")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(330)
        self.store = PipelineStore()
        self.pipelines: list[PipelineDefinition] = []
        self.current_pipeline: PipelineDefinition | None = None
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_profiles)
        self.runner = PipelineRunner(main_window)

        container = QWidget()
        container.setObjectName("pipelineEditorRoot")
        root = QVBoxLayout(container)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("pipelineHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(13, 11, 13, 11)
        hero_layout.setSpacing(5)
        title = QLabel("AUTOMATION FLOW")
        title.setObjectName("pipelineHeroTitle")
        subtitle = QLabel("Build once. Run every stage in order.")
        subtitle.setObjectName("pipelineHeroSubtitle")
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        root.addWidget(hero)

        profile_row = QHBoxLayout()
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
        root.addLayout(profile_row)

        self.step_list = PipelineStepList()
        self.step_list.order_changed.connect(self._steps_reordered)
        root.addWidget(self.step_list, 1)

        add_row = QHBoxLayout()
        self.add_step_button = QPushButton("+ Add step")
        self.add_step_button.setObjectName("pipelineAddStep")
        self.add_step_button.clicked.connect(self._show_add_step_menu)
        add_row.addWidget(self.add_step_button)
        add_row.addStretch(1)
        root.addLayout(add_row)

        run_panel = QFrame()
        run_panel.setObjectName("pipelineRunPanel")
        run_layout = QVBoxLayout(run_panel)
        run_layout.setContentsMargins(10, 9, 10, 9)
        run_layout.setSpacing(7)
        scope_row = QHBoxLayout()
        scope_label = QLabel("Scope")
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Current image", "Selected images", "Filtered images", "All images"])
        scope_row.addWidget(scope_label)
        scope_row.addWidget(self.scope_combo, 1)
        run_layout.addLayout(scope_row)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("pipelineStatus")
        run_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        run_layout.addWidget(self.progress_bar)
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
        root.addWidget(run_panel)
        self.setWidget(container)
        self._apply_style()

        self.runner.running_changed.connect(self._running_changed)
        self.runner.step_started.connect(self._step_started)
        self.runner.progress_changed.connect(self._progress_changed)
        self.runner.log_message.connect(self._append_log)
        self.runner.finished.connect(self._run_finished)
        self._load_profiles()

    def _apply_style(self):
        self.widget().setStyleSheet(
            """
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
        )

    def _marking_models(self) -> list[str]:
        root = settings.value("marking_models_directory_path", DEFAULT_SETTINGS["marking_models_directory_path"], type=str)
        if not root:
            return []
        base = Path(root)
        return [str(path.relative_to(base)) for path in sorted(base.glob("**/*.pt"))]

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
            card.changed.connect(self._schedule_save)
            card.delete_requested.connect(self._delete_step)
            row_widget = PipelineStepRow(card, self.step_list)
            item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
            self.step_list.addItem(item)
            self.step_list.setItemWidget(item, row_widget)

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
        self._schedule_save()

    def _schedule_save(self):
        if not self._loading:
            self._save_timer.start()

    def _save_profiles(self):
        try:
            self.store.save(self.pipelines)
        except (OSError, PipelineValidationError) as exc:
            self.status_label.setText(f"Save failed: {exc}")

    def _scope_indices(self) -> list[QModelIndex]:
        scope = self.scope_combo.currentText()
        source_model = self.main_window.image_list_model
        proxy_model = self.main_window.proxy_image_list_model
        if scope == "Current image":
            current = self.main_window.image_list.list_view.currentIndex()
            return [proxy_model.mapToSource(current)] if current.isValid() else []
        if scope == "Selected images":
            return self.main_window.image_list.get_selected_image_indices()
        if scope == "Filtered images":
            indices = []
            for row in range(proxy_model.rowCount()):
                proxy_index = proxy_model.index(row, 0)
                if proxy_index.data(Qt.ItemDataRole.UserRole) is not None:
                    indices.append(proxy_model.mapToSource(proxy_index))
            return indices
        return [source_model.index(row, 0) for row in range(source_model.rowCount())]

    def _run_or_cancel(self):
        if self.runner.is_running:
            self.runner.cancel()
            return
        if self.current_pipeline is None:
            return
        self._save_profiles()
        self.log_edit.clear()
        try:
            self.runner.run_pipeline(self.current_pipeline, self._scope_indices())
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
        self.progress_bar.show()

    def _progress_changed(self, value: int, total: int, title: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{title}  %v / %m")

    def _append_log(self, message: str):
        text = str(message or "").strip()
        if text:
            self.log_edit.appendPlainText(text)

    def _run_finished(self, success: bool, message: str):
        self.status_label.setText(message)
        if success:
            self.progress_bar.setValue(self.progress_bar.maximum())
        else:
            self.progress_bar.hide()

    def _toggle_log(self, visible: bool):
        self.log_edit.setVisible(visible)
