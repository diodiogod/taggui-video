import os
from pathlib import Path

from PySide6.QtCore import Signal, QModelIndex, Qt, Slot, QTimer, QSize, QEvent
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QDockWidget, QProgressBar, QPlainTextEdit,
                               QWidget, QVBoxLayout, QScrollArea,
                               QFrame, QFormLayout,
                               QMessageBox, QTableWidget, QHeaderView, QLabel,
                               QTableWidgetItem, QComboBox,
                               QHBoxLayout, QToolButton, QStyle, QLineEdit,
                               QListWidget, QListWidgetItem, QSizePolicy,
                               QAbstractItemView, QLayout)

from utils.icons import create_add_box_icon
from utils.auto_marking_preferences import (
    CLASS_ACTIONS_SETTINGS_KEY,
    CLASS_LABELS_SETTINGS_KEY,
    load_saved_class_values,
    save_saved_class_values,
)
from models.image_list_model import ImageListModel
from utils.utils import pluralize
from utils.big_widgets import TallPushButton
from utils.settings import settings, DEFAULT_SETTINGS
from utils.marking_model_security import (
    list_marking_model_paths,
    open_virustotal_for_file,
    passive_model_warning_text,
    preferred_runtime_path,
    prompt_resolve_runtime_path,
)
from utils.settings_widgets import (FocusedScrollSettingsComboBox,
                                    FocusedScrollSettingsDoubleSpinBox,
                                    FocusedScrollSettingsSpinBox,
                                    SettingsBigCheckBox)
from widgets.auto_captioner import set_text_edit_height, restore_stdout_and_stderr
from widgets.image_list import ImageList


def _startup_delay_ms(env_name: str, default_ms: int) -> int:
    try:
        return max(0, int(os.getenv(env_name, str(default_ms)) or default_ms))
    except (TypeError, ValueError):
        return max(0, int(default_ms))


class CompressibleAutoMarkingsRoot(QWidget):
    def minimumSizeHint(self):
        return QSize(0, 0)


class CompressibleScrollArea(QScrollArea):
    def minimumSizeHint(self):
        return QSize(0, 0)


class MarkingModelComboBox(FocusedScrollSettingsComboBox):
    _SORT_LABELS = {
        'name': 'Name',
        'recent': 'Recent',
    }

    def __init__(self, key: str | None = None):
        super().__init__(key=key)
        self._entries: list[tuple[str, Path, int]] = []
        self._popup: QFrame | None = None
        self._filter_edit: QLineEdit | None = None
        self._sort_button: QToolButton | None = None
        self._list_widget: QListWidget | None = None
        self._updating_entries = False

    def sort_mode(self) -> str:
        mode = str(settings.value('marking_model_sort_mode', 'name', type=str) or 'name')
        return mode if mode in self._SORT_LABELS else 'name'

    def set_sort_mode(self, mode: str):
        normalized = str(mode or 'name').strip().lower()
        if normalized not in self._SORT_LABELS:
            normalized = 'name'
        settings.setValue('marking_model_sort_mode', normalized)
        self._rebuild_combo_items()
        self._refresh_popup_contents()

    def toggle_sort_mode(self):
        self.set_sort_mode('recent' if self.sort_mode() == 'name' else 'name')

    def set_model_entries(self, entries: list[tuple[str, Path, int]], selected_text: str = ''):
        self._entries = list(entries)
        self._rebuild_combo_items(selected_text=selected_text)
        self._refresh_popup_contents()

    def showPopup(self):
        if self._popup is None:
            self._build_popup()
        self._refresh_popup_contents()
        popup = self._popup
        if popup is None:
            return
        available = self.screen().availableGeometry()
        popup_width = min(
            max(self.width(), 380),
            max(180, available.width() - 16),
        )
        popup_height = min(
            460,
            max(180, 56 + max(1, self._visible_entry_count()) * 28),
            max(180, available.height() - 16),
        )
        popup.setFixedWidth(popup_width)
        popup.resize(popup_width, popup_height)
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        popup_x = max(
            available.left() + 8,
            min(anchor.x(), available.right() - popup_width - 8),
        )
        popup_y = anchor.y()
        if popup_y + popup_height > available.bottom() - 8:
            popup_y = self.mapToGlobal(self.rect().topLeft()).y() - popup_height
        popup_y = max(
            available.top() + 8,
            min(popup_y, available.bottom() - popup_height - 8),
        )
        popup.move(popup_x, popup_y)
        popup.show()
        popup.raise_()
        popup.activateWindow()
        if self._filter_edit is not None:
            self._filter_edit.clear()
            self._filter_edit.setFocus()

    def hidePopup(self):
        if self._popup is not None:
            self._popup.hide()

    def _visible_entry_count(self) -> int:
        if self._list_widget is None:
            return len(self._entries)
        return self._list_widget.count()

    def _build_popup(self):
        popup = QFrame(None, Qt.WindowType.Popup)
        popup.setObjectName('markingModelPopup')
        popup.setStyleSheet(
            'QFrame#markingModelPopup { background: #25262B; border: 1px solid #4B5563; border-radius: 8px; }'
            'QLineEdit { background: #1E1E24; color: #F3F4F6; border: 1px solid #4B5563; border-radius: 5px; padding: 6px 8px; }'
            'QListWidget { background: transparent; color: #F3F4F6; border: 0; padding: 2px; }'
            'QListWidget::item { padding: 6px 8px; border-radius: 4px; }'
            'QListWidget::item:selected { background: #3B82F6; color: #FFFFFF; }'
            'QToolButton { color: #D1D5DB; background: #303139; border: 1px solid #4B5563; border-radius: 5px; padding: 5px 8px; }'
            'QToolButton:hover { color: #FFFFFF; border-color: #6B7280; background: #393B44; }'
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText('Filter models...')
        filter_edit.textChanged.connect(self._refresh_popup_contents)
        controls.addWidget(filter_edit, 1)
        sort_button = QToolButton()
        sort_button.clicked.connect(self.toggle_sort_mode)
        controls.addWidget(sort_button)
        layout.addLayout(controls)
        list_widget = QListWidget()
        list_widget.itemActivated.connect(self._popup_item_activated)
        list_widget.itemClicked.connect(self._popup_item_activated)
        layout.addWidget(list_widget, 1)
        self._popup = popup
        self._filter_edit = filter_edit
        self._sort_button = sort_button
        self._list_widget = list_widget

    def _sorted_entries(self) -> list[tuple[str, Path, int]]:
        entries = list(self._entries)
        if self.sort_mode() == 'recent':
            return sorted(entries, key=lambda item: (-item[2], item[0].casefold()))
        return sorted(entries, key=lambda item: item[0].casefold())

    def _rebuild_combo_items(self, selected_text: str = ''):
        current_text = selected_text or str(self.currentText() or '')
        current_data = self.currentData()
        entries = self._sorted_entries()
        previous = self.blockSignals(True)
        self._updating_entries = True
        try:
            self.clear()
            for text, path, _mtime_ns in entries:
                self.addItem(text, userData=path)
            if current_text and self.findText(current_text) >= 0:
                self.setCurrentText(current_text)
            elif current_text and self.isEditable():
                self.setEditText(current_text)
            elif current_data is not None:
                for index, (_text, path, _mtime_ns) in enumerate(entries):
                    if path == current_data:
                        self.setCurrentIndex(index)
                        break
            elif self.count() > 0:
                self.setCurrentIndex(0)
        finally:
            self._updating_entries = False
            self.blockSignals(previous)

    def _refresh_popup_contents(self):
        if self._sort_button is not None:
            self._sort_button.setText(self._SORT_LABELS[self.sort_mode()])
            self._sort_button.setToolTip('Toggle model ordering: name or most recently modified')
        if self._list_widget is None:
            return
        filter_text = str(self._filter_edit.text() if self._filter_edit is not None else '').strip().casefold()
        current_path = self.currentData()
        self._list_widget.clear()
        for text, path, _mtime_ns in self._sorted_entries():
            haystack = f'{text} {path.name}'.casefold()
            if filter_text and filter_text not in haystack:
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(str(path))
            self._list_widget.addItem(item)
            if current_path is not None and path == current_path:
                self._list_widget.setCurrentItem(item)

    def _popup_item_activated(self, item):
        if item is None:
            return
        selected_path = item.data(Qt.ItemDataRole.UserRole)
        selected_text = str(item.text() or '')
        if selected_text and self.findText(selected_text) >= 0:
            self.setCurrentText(selected_text)
        elif selected_path is not None:
            for index in range(self.count()):
                if self.itemData(index) == selected_path:
                    self.setCurrentIndex(index)
                    break
        self.hidePopup()
        self.activated.emit(self.currentIndex())


class MarkingSettingsForm(QWidget):
    model_selected = Signal(bool)
    model_activated = Signal()
    models_refreshed = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName('autoMarkingsSettings')
        self.setMinimumSize(0, 0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        root = QVBoxLayout(self)
        self.root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        model_title = QLabel('MODEL')
        model_title.setObjectName('autoMarkingsSectionTitle')
        model_subtitle = QLabel(
            'Choose a detector, then decide how each class becomes a marking.'
        )
        model_subtitle.setObjectName('autoMarkingsSectionSubtitle')
        model_subtitle.setWordWrap(True)
        root.addWidget(model_title)
        root.addWidget(model_subtitle)

        self.model_combo_box = MarkingModelComboBox(key='marking_model_id')
        self.model_combo_box.setPlaceholderText('Set marking model directory in "Settings..."')
        self.model_combo_box.activated.connect(self._on_model_activated)
        self.model_combo_box.currentTextChanged.connect(self._on_model_text_changed)
        model_selector = QWidget()
        model_selector.setObjectName('autoMarkingsModelRow')
        model_selector_layout = QHBoxLayout(model_selector)
        self.model_selector_layout = model_selector_layout
        model_selector_layout.setContentsMargins(0, 0, 0, 0)
        model_selector_layout.setSpacing(6)
        model_selector_layout.addWidget(self.model_combo_box, 1)
        self.rescan_models_button = QToolButton()
        self.rescan_models_button.setIcon(
            self.model_combo_box.style().standardIcon(
                QStyle.StandardPixmap.SP_BrowserReload
            )
        )
        self.rescan_models_button.setToolTip(
            'Rescan the auto-marking models directory'
        )
        self.rescan_models_button.clicked.connect(self.get_local_model_paths)
        model_selector_layout.addWidget(self.rescan_models_button)
        self.scan_model_button = QToolButton()
        self.scan_model_button.setText("VT")
        self.scan_model_button.setToolTip(
            "Open the selected model hash on VirusTotal"
        )
        self.scan_model_button.clicked.connect(self.open_selected_model_on_virustotal)
        model_selector_layout.addWidget(self.scan_model_button)
        root.addWidget(model_selector)
        QTimer.singleShot(
            _startup_delay_ms('TAGGUI_AUTO_MARKING_STARTUP_DELAY_MS', 6000),
            self.get_local_model_paths,
        )
        settings.change.connect(lambda key, value: self.get_local_model_paths()
            if key == 'marking_models_directory_path' else 0)
        self.model_warning_label = QLabel()
        self.model_warning_label.setWordWrap(True)
        self.model_warning_label.hide()
        self.model_warning_label.setObjectName('autoMarkingsWarning')
        root.addWidget(self.model_warning_label)

        class_header = QWidget()
        class_header_layout = QHBoxLayout(class_header)
        self.class_header_layout = class_header_layout
        class_header_layout.setContentsMargins(0, 5, 0, 0)
        class_header_layout.setSpacing(6)
        self.class_title_label = QLabel('CLASS MAPPING')
        self.class_title_label.setObjectName('autoMarkingsSectionTitle')
        class_header_layout.addWidget(self.class_title_label)
        class_header_layout.addStretch(1)
        self.reset_class_labels_button = QToolButton()
        self.reset_class_labels_button.setText('Reset labels')
        self.reset_class_labels_button.setToolTip(
            'Discard custom output labels for the selected model.'
        )
        self.reset_class_labels_button.setEnabled(False)
        class_header_layout.addWidget(self.reset_class_labels_button)
        root.addWidget(class_header)

        self.class_table = QTableWidget(0, 3)
        self.class_table.setObjectName('autoMarkingsClassTable')
        self.class_table.setHorizontalHeaderLabels(
            ['Model class', 'Output label', 'Marking']
        )
        header = self.class_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.class_table.verticalHeader().hide()
        self.class_table.verticalHeader().setDefaultSectionSize(30)
        self.class_table.setShowGrid(False)
        self.class_table.setAlternatingRowColors(True)
        self.class_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.class_table.setMinimumHeight(140)
        self.class_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        root.addWidget(self.class_table, 1)

        self.toggle_advanced_settings_form_button = QToolButton()
        self.toggle_advanced_settings_form_button.setObjectName(
            'autoMarkingsAdvancedToggle'
        )
        self.toggle_advanced_settings_form_button.setText('Advanced settings')
        self.toggle_advanced_settings_form_button.setCheckable(True)
        self.toggle_advanced_settings_form_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_advanced_settings_form_button.setArrowType(
            Qt.ArrowType.RightArrow
        )

        self.advanced_settings_form_container = QFrame()
        self.advanced_settings_form_container.setObjectName(
            'autoMarkingsAdvancedPanel'
        )
        advanced_settings_form = QFormLayout(
            self.advanced_settings_form_container)
        self.advanced_settings_form = advanced_settings_form
        advanced_settings_form.setContentsMargins(10, 8, 10, 8)
        advanced_settings_form.setHorizontalSpacing(10)
        advanced_settings_form.setVerticalSpacing(6)
        advanced_settings_form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows
        )
        advanced_settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        advanced_settings_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # Sets the minimum confidence threshold for detections.
        # Objects detected with confidence below this threshold will be
        # disregarded. Adjusting this value can help reduce false positives.
        self.confidence_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='confidence', default=0.25, minimum=0.01, maximum=1.0)
        self.confidence_spin_box.setSingleStep(0.01)
        advanced_settings_form.addRow('Confidence',
                                      self.confidence_spin_box)
        # Intersection Over Union (IoU) threshold for Non-Maximum Suppression
        # (NMS). Lower values result in fewer detections by eliminating
        # overlapping boxes, useful for reducing duplicates.
        self.iou_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='iou', default=0.7, minimum=0.01, maximum=1.0)
        self.iou_spin_box.setSingleStep(0.01)
        advanced_settings_form.addRow('Intersection Over Union (IoU)',
                                      self.iou_spin_box)
        # Maximum number of detections allowed per image.
        # Limits the total number of objects the model can detect in a single
        # inference, preventing excessive outputs in dense scenes.
        self.max_det_spin_box = FocusedScrollSettingsSpinBox(
            key='max_det', default=300, minimum=1, maximum=500)
        advanced_settings_form.addRow('Maximum number of detections', self.max_det_spin_box)
        self.merge_overlaps_check_box = SettingsBigCheckBox(
            key='auto_marking_merge_overlaps',
            default=DEFAULT_SETTINGS['auto_marking_merge_overlaps'],
            text='Merge overlapping detections')
        advanced_settings_form.addRow('Post-process', self.merge_overlaps_check_box)
        self.merge_overlap_threshold_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='auto_marking_merge_overlap_threshold',
            default=DEFAULT_SETTINGS['auto_marking_merge_overlap_threshold'],
            minimum=0.01,
            maximum=1.0)
        self.merge_overlap_threshold_spin_box.setSingleStep(0.05)
        advanced_settings_form.addRow('Merge overlap threshold',
                                      self.merge_overlap_threshold_spin_box)
        self.advanced_settings_form_container.hide()

        root.addWidget(self.toggle_advanced_settings_form_button)
        root.addWidget(self.advanced_settings_form_container)

        self.toggle_advanced_settings_form_button.toggled.connect(
            self.toggle_advanced_settings_form)

    @Slot(str)
    def _on_model_text_changed(self, text: str):
        settings.setValue('marking_model_id', text)
        self._refresh_model_warning()
        self.model_selected.emit(bool(text))

    @Slot(int)
    def _on_model_activated(self, _index: int):
        self._refresh_model_warning()
        self.model_selected.emit(bool(self.model_combo_box.currentText()))
        self.model_activated.emit()

    def _refresh_model_warning(self):
        warning_text = passive_model_warning_text(
            self.model_combo_box.currentData()
        )
        self.model_warning_label.setText(warning_text)
        self.model_warning_label.setVisible(bool(warning_text))

    def get_local_model_paths(self):
        models_directory_path = settings.value(
            'marking_models_directory_path',
            defaultValue=DEFAULT_SETTINGS['marking_models_directory_path'],
            type=str)
        previous_text = str(self.model_combo_box.currentText() or '')
        previous_path = self.model_combo_box.currentData()
        if not models_directory_path:
            previous = self.model_combo_box.blockSignals(True)
            self.model_combo_box.clear()
            self.model_combo_box.setPlaceholderText(
                'Set marking model directory in "Settings..."'
            )
            self.model_combo_box.blockSignals(previous)
            settings.setValue('marking_model_id', '')
            self._refresh_model_warning()
            self.models_refreshed.emit([])
            if previous_path is not None or previous_text:
                self.model_selected.emit(False)
            return []
        models_directory_path = Path(models_directory_path)
        print(f'Loading local auto-marking model paths under '
              f'{models_directory_path}...')
        config_paths = list_marking_model_paths(models_directory_path)
        saved_text = str(
            settings.value('marking_model_id', '', type=str) or previous_text
        )
        if saved_text and saved_text.endswith('.pt'):
            preferred_saved_text = str(Path(saved_text).with_suffix('.onnx')).replace("\\", "/")
            if any(
                str(path.relative_to(models_directory_path)).replace("\\", "/") == preferred_saved_text
                for path in config_paths
            ):
                saved_text = preferred_saved_text
        if len(config_paths) == 0:
            previous = self.model_combo_box.blockSignals(True)
            self.model_combo_box.clear()
            self.model_combo_box.setPlaceholderText(
                'Set marking model directory in "Settings..."')
            self.model_combo_box.blockSignals(previous)
        else:
            self.model_combo_box.setPlaceholderText('Select marking model')
            entries = [
                (
                    str(path.relative_to(models_directory_path)).replace("\\", "/"),
                    path,
                    path.stat().st_mtime_ns if path.exists() else 0,
                )
                for path in config_paths
            ]
            self.model_combo_box.set_model_entries(entries, selected_text=saved_text)
        current_text = str(self.model_combo_box.currentText() or '')
        current_path = self.model_combo_box.currentData()
        settings.setValue('marking_model_id', current_text)
        self._refresh_model_warning()
        relative_paths = [
            str(path.relative_to(models_directory_path)) for path in config_paths
        ]
        self.models_refreshed.emit(relative_paths)
        if current_path != previous_path or current_text != previous_text:
            self.model_selected.emit(bool(current_text))
        return relative_paths

    @Slot()
    def open_selected_model_on_virustotal(self):
        selected_path = self.model_combo_box.currentData()
        if selected_path is None:
            return
        open_virustotal_for_file(Path(selected_path), parent=self.model_combo_box.window())

    @Slot(bool)
    def toggle_advanced_settings_form(self, expanded: bool):
        self.advanced_settings_form_container.setVisible(expanded)
        self.toggle_advanced_settings_form_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def get_marking_settings(self) -> dict:
        return {
            'model_path': self.model_combo_box.currentData(),
            'requested_model_path': self.model_combo_box.currentData(),
            'conf': self.confidence_spin_box.value(),
            'iou': self.iou_spin_box.value(),
            'max_det': self.max_det_spin_box.value(),
            'merge_overlaps': self.merge_overlaps_check_box.isChecked(),
            'merge_overlap_threshold': self.merge_overlap_threshold_spin_box.value(),
            'classes': None
        }

    def set_class_count(self, count: int):
        suffix = f' ({count})' if count > 0 else ''
        self.class_title_label.setText(f'CLASS MAPPING{suffix}')

    def apply_ui_zoom(self, scale: float):
        spacing = max(3, round(8 * scale))
        self.root_layout.setSpacing(spacing)
        self.model_selector_layout.setSpacing(max(2, round(6 * scale)))
        self.class_header_layout.setSpacing(max(2, round(6 * scale)))
        self.class_header_layout.setContentsMargins(
            0, max(2, round(5 * scale)), 0, 0
        )
        self.advanced_settings_form.setContentsMargins(
            max(5, round(10 * scale)),
            max(4, round(8 * scale)),
            max(5, round(10 * scale)),
            max(4, round(8 * scale)),
        )
        self.advanced_settings_form.setHorizontalSpacing(
            max(4, round(10 * scale))
        )
        self.advanced_settings_form.setVerticalSpacing(
            max(3, round(6 * scale))
        )
        self.class_table.verticalHeader().setDefaultSectionSize(
            max(20, round(30 * scale))
        )
        self.class_table.setMinimumHeight(max(90, round(140 * scale)))

class AutoMarkings(QDockWidget):
    marking_generated = Signal(QModelIndex, list)
    _CLASS_ACTIONS_SETTINGS_KEY = CLASS_ACTIONS_SETTINGS_KEY
    _CLASS_LABELS_SETTINGS_KEY = CLASS_LABELS_SETTINGS_KEY

    def __init__(self, image_list_model: ImageListModel,
                 image_list: ImageList, parent):
        super().__init__(parent)
        self.main_window = parent
        self.image_list_model = image_list_model
        self.image_list = image_list
        self.is_marking = False
        self.marking_thread = None
        self.show_alert_when_finished = False
        self._run_marking_count = 0
        self._run_processed_image_count = 0
        self._run_expected_image_count = 0
        self._run_last_image_name = ''
        self.min_ui_zoom = 60
        self.max_ui_zoom = 160
        self.ui_zoom_step = 10
        self.ui_zoom = max(
            self.min_ui_zoom,
            min(
                self.max_ui_zoom,
                settings.value(
                    'auto_markings_ui_zoom',
                    defaultValue=DEFAULT_SETTINGS['auto_markings_ui_zoom'],
                    type=int,
                ),
            ),
        )
        # Whether the last block of text in the console text edit should be
        # replaced with the next block of text that is outputted.
        self.replace_last_console_text_edit_block = False
        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('auto_markings')
        self.setWindowTitle('Auto-Markings')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea |
                             Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumSize(150, 80)

        self.start_cancel_button = TallPushButton('Start Auto-Marking')
        self.start_cancel_button.setObjectName('autoMarkingsPrimaryButton')
        self.start_cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName('autoMarkingsProgress')
        self.progress_bar.setFormat('%v / %m images marked (%p%)')
        self.progress_bar.hide()
        self.result_label = QLabel()
        self.result_label.setObjectName('autoMarkingsStatus')
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        self.log_button = QToolButton()
        self.log_button.setObjectName('autoMarkingsLogButton')
        self.log_button.setText('Log')
        self.log_button.setCheckable(True)
        self.log_button.setToolTip('Show or hide auto-marking output')
        self.console_text_edit = QPlainTextEdit()
        self.console_text_edit.setObjectName('autoMarkingsConsole')
        set_text_edit_height(self.console_text_edit, 4)
        self.console_text_edit.setReadOnly(True)
        self.console_text_edit.setMinimumHeight(72)
        self.console_text_edit.setMaximumHeight(180)
        self.console_text_edit.setFixedHeight(96)
        self.console_panel = QWidget()
        self.console_panel.setObjectName('autoMarkingsConsolePanel')
        console_layout = QVBoxLayout(self.console_panel)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(4)
        console_layout.addWidget(self.console_text_edit)
        self.console_panel.hide()

        self.marking_settings_form = MarkingSettingsForm()
        self.settings_scroll_area = CompressibleScrollArea()
        self.settings_scroll_area.setObjectName('autoMarkingsSettingsScroll')
        self.settings_scroll_area.setWidgetResizable(True)
        self.settings_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.settings_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll_area.setWidget(self.marking_settings_form)
        self.settings_scroll_area.setMinimumSize(0, 0)
        self.settings_scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )

        self.run_panel = QFrame()
        self.run_panel.setObjectName('autoMarkingsRunPanel')
        self.run_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        run_layout = QVBoxLayout(self.run_panel)
        self.run_layout = run_layout
        run_layout.setContentsMargins(0, 8, 0, 0)
        run_layout.setSpacing(6)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(self.result_label, 1)
        status_row.addWidget(self.log_button)
        run_layout.addLayout(status_row)
        run_layout.addWidget(self.progress_bar)
        run_layout.addWidget(self.console_panel)
        run_layout.addWidget(self.start_cancel_button)

        container = CompressibleAutoMarkingsRoot()
        container.setObjectName('autoMarkingsRoot')
        container.setMinimumSize(0, 0)
        container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        layout = QVBoxLayout(container)
        self.root_layout = layout
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.settings_scroll_area, 1)
        layout.addWidget(self.run_panel)
        self.setWidget(container)
        self._install_ui_zoom_filters()
        self._apply_ui_zoom()

        self.start_cancel_button.clicked.connect(
            self.start_or_cancel_marking)
        self.log_button.toggled.connect(self._toggle_console_panel)
        self.marking_settings_form.model_selected.connect(self._on_model_selection_changed)
        self.marking_settings_form.model_activated.connect(
            self._on_model_activated
        )
        self.marking_settings_form.models_refreshed.connect(
            self._on_models_refreshed
        )
        self.marking_settings_form.class_table.itemChanged.connect(
            self._on_class_label_changed
        )
        self.marking_settings_form.reset_class_labels_button.clicked.connect(
            self._reset_class_labels
        )
        QTimer.singleShot(
            _startup_delay_ms('TAGGUI_AUTO_MARKING_RESTORE_DELAY_MS', 6500),
            self._restore_model_selection_state,
        )

    def minimumSizeHint(self):
        return QSize(150, 80)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_primary_button_text()
        width = self.width()
        self.marking_settings_form.reset_class_labels_button.setText(
            'Reset labels' if width >= 300 else 'Reset'
        )

    def _install_ui_zoom_filters(self):
        root = self.widget()
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
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
        settings.setValue('auto_markings_ui_zoom', new_zoom)
        self._apply_ui_zoom()

    def _apply_ui_zoom(self):
        scale = self.ui_zoom / 100.0
        margin = max(4, round(8 * scale))
        self.root_layout.setContentsMargins(margin, margin, margin, margin)
        self.root_layout.setSpacing(max(4, round(8 * scale)))
        self.run_layout.setContentsMargins(
            0, max(4, round(8 * scale)), 0, 0
        )
        self.run_layout.setSpacing(max(3, round(6 * scale)))
        self.marking_settings_form.apply_ui_zoom(scale)
        self.console_text_edit.setFixedHeight(max(64, round(96 * scale)))
        self._apply_style()

    def _update_primary_button_text(self, *, canceling: bool = False):
        if canceling:
            full_text = 'Canceling Auto-Marking...'
            compact_text = 'Canceling...'
        elif self.is_marking:
            full_text = 'Cancel Auto-Marking'
            compact_text = 'Cancel'
        else:
            full_text = 'Start Auto-Marking'
            compact_text = 'Start'
        self.start_cancel_button.setText(
            full_text if self.width() >= 230 else compact_text
        )

    @Slot(bool)
    def _toggle_console_panel(self, visible: bool):
        self.console_panel.setVisible(visible)
        if visible:
            self.log_button.setText('Log')

    def _apply_style(self):
        scale = self.ui_zoom / 100.0
        base_style = """
            QWidget#autoMarkingsRoot {
                background: #2B2B2B;
                color: #F3F4F6;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 12px;
            }
            QScrollArea#autoMarkingsSettingsScroll {
                background: transparent;
                border: 0;
            }
            QScrollArea#autoMarkingsSettingsScroll > QWidget > QWidget {
                background: transparent;
            }
            QWidget#autoMarkingsSettings {
                background: transparent;
            }
            QLabel#autoMarkingsSectionTitle {
                color: #DDE3EA;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#autoMarkingsSectionSubtitle {
                color: #9CA3AF;
                font-size: 11px;
            }
            QLabel#autoMarkingsWarning {
                color: #F2B84B;
                background: #332C20;
                border-left: 2px solid #D99A32;
                padding: 6px 8px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: #1E1E24;
                color: #F3F4F6;
                border: 1px solid #4B5563;
                border-radius: 5px;
                padding: 5px 7px;
                min-height: 27px;
                selection-background-color: #3B82F6;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
            QDoubleSpinBox:focus {
                border-color: #3B82F6;
            }
            QComboBox QAbstractItemView {
                background: #25262B;
                color: #F3F4F6;
                border: 1px solid #4B5563;
                selection-background-color: #3B82F6;
            }
            QToolButton {
                color: #D1D5DB;
                background: transparent;
                border: 1px solid #4B5563;
                border-radius: 5px;
                padding: 5px 7px;
            }
            QToolButton:hover {
                color: #FFFFFF;
                background: #35363E;
                border-color: #6B7280;
            }
            QToolButton:disabled {
                color: #6B7280;
                border-color: #3A3D44;
            }
            QToolButton#autoMarkingsAdvancedToggle {
                border: 0;
                border-top: 1px solid #42454D;
                border-radius: 0;
                padding: 8px 2px 3px 2px;
                text-align: left;
                font-weight: 600;
            }
            QToolButton#autoMarkingsAdvancedToggle:hover {
                background: transparent;
                color: #60A5FA;
            }
            QFrame#autoMarkingsAdvancedPanel {
                background: #25262B;
                border: 0;
                border-radius: 6px;
            }
            QTableWidget#autoMarkingsClassTable {
                background: #24252A;
                alternate-background-color: #292A30;
                color: #E5E7EB;
                border: 1px solid #42454D;
                border-radius: 6px;
                outline: 0;
                selection-background-color: #334C70;
            }
            QTableWidget#autoMarkingsClassTable::item {
                border: 0;
                padding: 4px 6px;
            }
            QHeaderView::section {
                background: #303139;
                color: #BFC7D2;
                border: 0;
                border-bottom: 1px solid #4B4E57;
                padding: 6px;
                font-size: 10px;
                font-weight: 600;
            }
            QTableCornerButton::section {
                background: #303139;
                border: 0;
            }
            QFrame#autoMarkingsRunPanel {
                background: transparent;
                border: 0;
                border-top: 1px solid #42454D;
            }
            QLabel#autoMarkingsStatus {
                color: #CBD5E1;
                font-size: 11px;
                padding: 2px 0;
            }
            QToolButton#autoMarkingsLogButton {
                border: 0;
                padding: 3px 5px;
                color: #9CA3AF;
            }
            QToolButton#autoMarkingsLogButton:checked {
                color: #60A5FA;
            }
            QPlainTextEdit#autoMarkingsConsole {
                background: #1E1E24;
                color: #CBD5E1;
                border: 1px solid #42454D;
                border-radius: 5px;
                padding: 5px;
                font-family: Consolas, monospace;
                font-size: 10px;
            }
            QProgressBar#autoMarkingsProgress {
                color: #E5E7EB;
                background: #1E1E24;
                border: 1px solid #4B5563;
                border-radius: 4px;
                text-align: center;
                min-height: 15px;
                max-height: 17px;
                font-size: 10px;
            }
            QProgressBar#autoMarkingsProgress::chunk {
                background: #3B82F6;
                border-radius: 3px;
            }
            QPushButton#autoMarkingsPrimaryButton {
                color: #FFFFFF;
                background: #3B82F6;
                border: 0;
                border-radius: 6px;
                padding: 7px 10px;
                min-height: 28px;
                max-height: 30px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton#autoMarkingsPrimaryButton:hover {
                background: #2563EB;
            }
            QPushButton#autoMarkingsPrimaryButton:disabled {
                color: #8C929D;
                background: #3A3C43;
            }
        """
        scaled_style = f"""
            QWidget#autoMarkingsRoot {{
                font-size: {max(8, round(12 * scale))}px;
            }}
            QLabel#autoMarkingsSectionTitle {{
                font-size: {max(8, round(11 * scale))}px;
                letter-spacing: {max(0, round(1 * scale))}px;
            }}
            QLabel#autoMarkingsSectionSubtitle {{
                font-size: {max(8, round(11 * scale))}px;
            }}
            QLabel#autoMarkingsWarning {{
                padding: {max(3, round(6 * scale))}px
                         {max(4, round(8 * scale))}px;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                font-size: {max(8, round(11 * scale))}px;
                padding: {max(2, round(5 * scale))}px
                         {max(4, round(7 * scale))}px;
                min-height: {max(18, round(27 * scale))}px;
            }}
            QToolButton {{
                font-size: {max(8, round(11 * scale))}px;
                padding: {max(2, round(5 * scale))}px
                         {max(3, round(7 * scale))}px;
            }}
            QToolButton#autoMarkingsAdvancedToggle {{
                padding: {max(4, round(8 * scale))}px
                         {max(1, round(2 * scale))}px
                         {max(2, round(3 * scale))}px
                         {max(1, round(2 * scale))}px;
            }}
            QTableWidget#autoMarkingsClassTable::item {{
                padding: {max(2, round(4 * scale))}px
                         {max(3, round(6 * scale))}px;
            }}
            QHeaderView::section {{
                padding: {max(3, round(6 * scale))}px;
                font-size: {max(8, round(10 * scale))}px;
            }}
            QLabel#autoMarkingsStatus {{
                font-size: {max(8, round(11 * scale))}px;
            }}
            QPlainTextEdit#autoMarkingsConsole {{
                padding: {max(3, round(5 * scale))}px;
                font-size: {max(8, round(10 * scale))}px;
            }}
            QProgressBar#autoMarkingsProgress {{
                min-height: {max(10, round(15 * scale))}px;
                max-height: {max(12, round(17 * scale))}px;
                font-size: {max(8, round(10 * scale))}px;
            }}
            QPushButton#autoMarkingsPrimaryButton {{
                padding: {max(4, round(7 * scale))}px
                         {max(5, round(10 * scale))}px;
                min-height: {max(20, round(28 * scale))}px;
                max-height: {max(22, round(30 * scale))}px;
                font-size: {max(8, round(11 * scale))}px;
            }}
        """
        self.widget().setStyleSheet(
            base_style + scaled_style
        )

    @Slot(bool)
    def _on_model_selection_changed(self, has_model_text: bool):
        self.marking_settings_form.reset_class_labels_button.setEnabled(
            has_model_text
        )
        if not has_model_text:
            self.start_cancel_button.setEnabled(False)
            return
        self.prepare_generation()

    @Slot()
    def _on_model_activated(self):
        requested_model_path = self.marking_settings_form.model_combo_box.currentData()
        if requested_model_path is None:
            return
        requested_model_path = Path(requested_model_path)
        if preferred_runtime_path(requested_model_path) == requested_model_path:
            if requested_model_path.suffix.lower() == '.pt':
                self.prepare_generation(interactive=True, purpose='inspect')

    @Slot(list)
    def _on_models_refreshed(self, model_paths: list[str]):
        pipeline_editor = getattr(self.main_window, 'pipeline_editor', None)
        if pipeline_editor is not None:
            pipeline_editor.refresh_marking_models(model_paths)

    def set_browser_context(
            self, image_list_model: ImageListModel, image_list: ImageList):
        """Target future runs at the active browser's independent model."""
        if (
            self.image_list_model is image_list_model
            and self.image_list is image_list
        ):
            return
        self.image_list_model = image_list_model
        self.image_list = image_list
        if not self.is_marking:
            self.marking_thread = None

    @Slot()
    def start_or_cancel_marking(self):
        if self.is_marking:
            # Cancel marking.
            self.marking_thread.is_canceled = True
            self.start_cancel_button.setEnabled(False)
            self._update_primary_button_text(canceling=True)
        else:
            # Start marking.
            self.generate_markings()

    @Slot()
    def _restore_model_selection_state(self):
        if self.marking_settings_form.model_combo_box.currentData() is None:
            return
        self.prepare_generation()

    def set_is_marking(self, is_marking: bool):
        self.is_marking = is_marking
        self._update_primary_button_text()

    def _current_model_key(self) -> str:
        return str(self.marking_settings_form.model_combo_box.currentText() or '').strip()

    @staticmethod
    def _load_saved_class_values(key: str) -> dict[str, dict[str, str]]:
        return load_saved_class_values(key)

    @staticmethod
    def _save_saved_class_values(
            key: str, payload: dict[str, dict[str, str]]):
        save_saved_class_values(key, payload)

    def _persist_class_actions_for_current_model(self):
        model_key = self._current_model_key()
        if not model_key:
            return
        payload = self._load_saved_class_values(
            self._CLASS_ACTIONS_SETTINGS_KEY
        )
        model_actions = {}
        row_count = self.marking_settings_form.class_table.rowCount()
        for row in range(row_count):
            class_item = self.marking_settings_form.class_table.item(row, 0)
            combo = self.marking_settings_form.class_table.cellWidget(row, 2)
            if class_item is None or combo is None:
                continue
            class_id = class_item.data(Qt.ItemDataRole.UserRole)
            if class_id is None:
                continue
            model_actions[str(class_id)] = str(combo.currentText() or 'ignore')
        payload[model_key] = model_actions
        self._save_saved_class_values(
            self._CLASS_ACTIONS_SETTINGS_KEY, payload
        )

    def _restore_class_actions_for_current_model(self):
        model_key = self._current_model_key()
        if not model_key:
            return
        payload = self._load_saved_class_values(
            self._CLASS_ACTIONS_SETTINGS_KEY
        )
        model_actions = payload.get(model_key, {})
        default_action = 'hint'
        row_count = self.marking_settings_form.class_table.rowCount()
        for row in range(row_count):
            class_item = self.marking_settings_form.class_table.item(row, 0)
            combo = self.marking_settings_form.class_table.cellWidget(row, 2)
            if class_item is None or combo is None:
                continue
            class_id = class_item.data(Qt.ItemDataRole.UserRole)
            action = model_actions.get(str(class_id), default_action)
            combo.setCurrentText(action)

    def _persist_class_labels_for_current_model(self):
        model_key = self._current_model_key()
        if not model_key:
            return
        payload = self._load_saved_class_values(
            self._CLASS_LABELS_SETTINGS_KEY
        )
        model_labels = {}
        table = self.marking_settings_form.class_table
        for row in range(table.rowCount()):
            class_item = table.item(row, 0)
            label_item = table.item(row, 1)
            if class_item is None or label_item is None:
                continue
            class_id = class_item.data(Qt.ItemDataRole.UserRole)
            default_label = str(
                label_item.data(Qt.ItemDataRole.UserRole) or ''
            ).strip()
            output_label = label_item.text().strip()
            if class_id is not None and output_label and output_label != default_label:
                model_labels[str(class_id)] = output_label
        if model_labels:
            payload[model_key] = model_labels
        else:
            payload.pop(model_key, None)
        self._save_saved_class_values(
            self._CLASS_LABELS_SETTINGS_KEY, payload
        )

    def _restore_class_labels_for_current_model(self):
        model_key = self._current_model_key()
        if not model_key:
            return
        payload = self._load_saved_class_values(
            self._CLASS_LABELS_SETTINGS_KEY
        )
        model_labels = payload.get(model_key, {})
        table = self.marking_settings_form.class_table
        previous = table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                class_item = table.item(row, 0)
                label_item = table.item(row, 1)
                if class_item is None or label_item is None:
                    continue
                class_id = class_item.data(Qt.ItemDataRole.UserRole)
                default_label = str(
                    label_item.data(Qt.ItemDataRole.UserRole) or ''
                )
                label_item.setText(
                    str(model_labels.get(str(class_id), default_label))
                )
        finally:
            table.blockSignals(previous)

    @Slot(QTableWidgetItem)
    def _on_class_label_changed(self, item: QTableWidgetItem):
        if item.column() == 1:
            self._persist_class_labels_for_current_model()

    @Slot()
    def _reset_class_labels(self):
        table = self.marking_settings_form.class_table
        previous = table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                label_item = table.item(row, 1)
                if label_item is not None:
                    label_item.setText(str(
                        label_item.data(Qt.ItemDataRole.UserRole) or ''
                    ))
        finally:
            table.blockSignals(previous)
        self._persist_class_labels_for_current_model()

    @Slot(str)
    def update_console_text_edit(self, text: str):
        # '\x1b[A' is the ANSI escape sequence for moving the cursor up.
        if text == '\x1b[A':
            self.replace_last_console_text_edit_block = True
            return
        text = text.strip()
        if not text:
            return
        if not self.log_button.isChecked():
            self.log_button.setText('Log *')
        if self.replace_last_console_text_edit_block:
            self.replace_last_console_text_edit_block = False
            # Select and remove the last block of text.
            self.console_text_edit.moveCursor(QTextCursor.MoveOperation.End)
            self.console_text_edit.moveCursor(
                QTextCursor.MoveOperation.StartOfBlock,
                QTextCursor.MoveMode.KeepAnchor)
            self.console_text_edit.textCursor().removeSelectedText()
            # Delete the newline.
            self.console_text_edit.textCursor().deletePreviousChar()
        self.console_text_edit.appendPlainText(text)

    @Slot()
    def show_alert(self):
        if self.marking_thread.is_canceled:
            return
        if self.marking_thread.is_error:
            icon = QMessageBox.Icon.Critical
            text = ('An error occurred during marking. See the '
                    'Auto-Marking console for more information.')
        else:
            icon = QMessageBox.Icon.Information
            text = self.result_label.text() or 'Auto-marking finished.'
        alert = QMessageBox()
        alert.setIcon(icon)
        alert.setText(text)
        alert.exec()

    @Slot(str, int)
    def update_result_label(self, image_name: str, marking_count: int):
        self._run_marking_count += max(0, marking_count)
        self._run_processed_image_count += 1
        self._run_last_image_name = image_name
        if marking_count <= 0:
            text = f'No markings found for {image_name}.'
        elif marking_count == 1:
            text = f'Found 1 marking for {image_name}.'
        else:
            text = f'Found {marking_count} markings for {image_name}.'
        self.result_label.setText(text)
        self.result_label.show()

    def _sync_selected_model_path(self, runtime_model_path: Path):
        models_directory_path = settings.value(
            'marking_models_directory_path',
            defaultValue=DEFAULT_SETTINGS['marking_models_directory_path'],
            type=str,
        )
        if not models_directory_path:
            return
        base = Path(models_directory_path)
        try:
            relative_text = str(
                Path(runtime_model_path).expanduser().relative_to(base)
            ).replace("\\", "/")
        except Exception:
            return
        self.marking_settings_form.get_local_model_paths()
        if self.marking_settings_form.model_combo_box.findText(relative_text) >= 0:
            self.marking_settings_form.model_combo_box.setCurrentText(relative_text)

    def prepare_generation(self, *, interactive: bool = False, purpose: str = 'run'):
        selected_image_indices = self.image_list.get_selected_image_indices()
        marking_settings = self.marking_settings_form.get_marking_settings()
        requested_model_path = marking_settings.get('requested_model_path')
        if requested_model_path is not None:
            requested_model_path = Path(requested_model_path)
            try:
                if interactive:
                    marking_settings['model_path'] = prompt_resolve_runtime_path(
                        requested_model_path,
                        parent=self,
                        purpose=purpose,
                    )
                    self._sync_selected_model_path(marking_settings['model_path'])
                else:
                    marking_settings['model_path'] = preferred_runtime_path(
                        requested_model_path
                    )
            except RuntimeError as exc:
                self.result_label.setText(str(exc))
                self.result_label.show()
                self.start_cancel_button.setEnabled(bool(requested_model_path))
                return
            if (not interactive
                    and Path(marking_settings['model_path']).suffix.lower() == '.pt'):
                self.marking_thread = None
                self.marking_settings_form.class_table.setRowCount(0)
                self.marking_settings_form.set_class_count(0)
                self.result_label.setText(
                    'PT model selected. TagGUI will offer a safer ONNX import '
                    'or explicit unsafe fallback when you run it.'
                )
                self.result_label.show()
                self.start_cancel_button.setEnabled(True)
                return
        from auto_marking.marking_thread import MarkingThread
        self.marking_thread = MarkingThread(
            self, self.image_list_model, selected_image_indices,
            marking_settings)
        self.marking_thread.text_outputted.connect(
            self.update_console_text_edit)
        self.marking_thread.clear_console_text_edit_requested.connect(
            self.console_text_edit.clear)
        self.marking_thread.marking_generated.connect(
            self._apply_generated_markings)
        self.marking_thread.marking_result.connect(
            self.update_result_label)
        self.marking_thread.progress_bar_update_requested.connect(
            self.progress_bar.setValue)
        self.marking_thread.finished.connect(
            lambda: self.set_is_marking(False))
        self.marking_thread.finished.connect(self._handle_marking_finished)
        self.marking_thread.finished.connect(restore_stdout_and_stderr)
        self.marking_thread.finished.connect(self.progress_bar.hide)
        self.marking_thread.finished.connect(
            lambda: self.start_cancel_button.setEnabled(True))
        if self.show_alert_when_finished:
            self.marking_thread.finished.connect(self.show_alert)
        self.marking_thread.preload_model()
        class_table = self.marking_settings_form.class_table
        if self.marking_thread.model is None:
            class_table.setRowCount(0)
            self.marking_settings_form.set_class_count(0)
            self.start_cancel_button.setEnabled(False)
            return
        previous = class_table.blockSignals(True)
        try:
            class_table.setRowCount(
                len(self.marking_thread.model.names))
            self.marking_settings_form.set_class_count(
                len(self.marking_thread.model.names)
            )
            for row, (class_id, class_name) in enumerate(
                    self.marking_thread.model.names.items()):
                class_item = QTableWidgetItem(str(class_name))
                class_item.setData(Qt.ItemDataRole.UserRole, int(class_id))
                class_item.setFlags(
                    class_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                class_table.setItem(row, 0, class_item)

                label_item = QTableWidgetItem(str(class_name))
                label_item.setData(
                    Qt.ItemDataRole.UserRole, str(class_name)
                )
                label_item.setToolTip(
                    'Double-click to customize the generated marking label.'
                )
                class_table.setItem(row, 1, label_item)

                combo = QComboBox()
                combo.addItem('ignore')
                combo.addItem(create_add_box_icon(Qt.gray), 'hint')
                combo.addItem(create_add_box_icon(Qt.red), 'exclude')
                combo.addItem(create_add_box_icon(Qt.green), 'include')
                combo.installEventFilter(self)
                combo.currentTextChanged.connect(
                    lambda _text, self=self: self._persist_class_actions_for_current_model()
                )
                class_table.setCellWidget(row, 2, combo)
        finally:
            class_table.blockSignals(previous)
        self._restore_class_labels_for_current_model()
        self._restore_class_actions_for_current_model()
        self.start_cancel_button.setEnabled(True)

    @Slot(QModelIndex, list)
    def _apply_generated_markings(
            self, image_index: QModelIndex, markings: list[dict]):
        thread = self.sender()
        target_model = getattr(thread, 'image_list_model', self.image_list_model)
        target_model.add_image_markings(image_index, markings)
        image = image_index.data(Qt.ItemDataRole.UserRole)
        viewer = getattr(self.main_window, 'image_viewer', None)
        if viewer is not None:
            viewer.refresh_marking_overlays(image)
        self.marking_generated.emit(image_index, markings)

    @Slot()
    def _handle_marking_finished(self):
        if self.marking_thread is None:
            return
        if self.marking_thread.is_canceled:
            self.result_label.setText('Auto-marking canceled.')
        elif self.marking_thread.is_error:
            self.result_label.setText(
                'Auto-marking failed. See the console for details.'
            )
        elif not self.marking_thread.marking_settings.get('classes'):
            self.result_label.setText('No classes enabled. Nothing was marked.')
        elif self._run_marking_count <= 0:
            image_count = (
                self._run_processed_image_count
                or self._run_expected_image_count
            )
            if image_count == 1 and self._run_last_image_name:
                text = f'No markings found for {self._run_last_image_name}.'
            else:
                text = f'No markings found in {image_count} images.'
            self.result_label.setText(text)
        else:
            image_count = (
                self._run_processed_image_count
                or self._run_expected_image_count
            )
            marking_label = (
                'marking' if self._run_marking_count == 1 else 'markings'
            )
            image_label = 'image' if image_count == 1 else 'images'
            self.result_label.setText(
                f'Found {self._run_marking_count} {marking_label} '
                f'in {image_count} {image_label}.'
            )
        self.result_label.show()

    @Slot()
    def generate_markings(self):
        selected_image_indices = self.image_list.get_selected_image_indices()
        self.prepare_generation(interactive=True)
        if self.marking_thread is None or self.marking_thread.model is None:
            self.start_cancel_button.setEnabled(False)
            return
        self.marking_thread.selected_image_indices = selected_image_indices
        self.marking_thread.marking_settings = self.marking_settings_form.get_marking_settings()
        self.marking_thread.marking_settings['model_path'] = self.marking_thread.model_path
        self.marking_thread.marking_settings['requested_model_path'] = (
            self.marking_thread.model_path
        )
        classes = {}
        for row, (class_id, class_name) in enumerate(
                self.marking_thread.model.names.items()):
            label_item = self.marking_settings_form.class_table.item(row, 1)
            output_label = (
                label_item.text().strip()
                if label_item is not None else ''
            ) or str(class_name)
            combo = self.marking_settings_form.class_table.cellWidget(
                row, 2
            ).currentText()
            if combo != 'ignore':
                classes[class_id] = (output_label, combo)
        self.marking_thread.marking_settings['classes'] = classes
        selected_image_count = len(selected_image_indices)
        self.image_list_model.add_to_undo_stack(
            action_name=f'Generate '
                        f'{pluralize('Marking', selected_image_count)}',
            should_ask_for_confirmation=selected_image_count > 1)
        if selected_image_count > 1:
            from dialogs.caption_multiple_images_dialog import CaptionMultipleImagesDialog

            confirmation_dialog = CaptionMultipleImagesDialog(
                selected_image_count, 'Mark', 'Markings')
            reply = confirmation_dialog.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.show_alert_when_finished = (confirmation_dialog
                                             .show_alert_check_box.isChecked())
        self._run_marking_count = 0
        self._run_processed_image_count = 0
        self._run_expected_image_count = selected_image_count
        self._run_last_image_name = ''
        self.set_is_marking(True)
        self.result_label.setText('Running auto-marking...')
        self.result_label.show()
        if selected_image_count > 1:
            self.progress_bar.setRange(0, selected_image_count)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
        self.marking_thread.start()
