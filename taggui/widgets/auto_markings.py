import sys
import json
import os
from pathlib import Path

from PySide6.QtCore import Signal, QModelIndex, Qt, Slot, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QDockWidget, QProgressBar, QPlainTextEdit,
                               QWidget, QVBoxLayout, QScrollArea,
                               QAbstractScrollArea, QFrame, QFormLayout,
                               QMessageBox, QTableWidget, QHeaderView, QLabel,
                               QTableWidgetItem, QComboBox, QPushButton,
                               QHBoxLayout, QToolButton, QStyle, QLineEdit,
                               QListWidget, QListWidgetItem)

from utils.icons import create_add_box_icon
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
from widgets.auto_captioner import (set_text_edit_height,
                                    restore_stdout_and_stderr, HorizontalLine)
from widgets.image_list import ImageList
from auto_marking.marking_thread import MarkingThread
from dialogs.caption_multiple_images_dialog import CaptionMultipleImagesDialog


def _startup_delay_ms(env_name: str, default_ms: int) -> int:
    try:
        return max(0, int(os.getenv(env_name, str(default_ms)) or default_ms))
    except (TypeError, ValueError):
        return max(0, int(default_ms))


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
        popup_width = max(self.width(), 380)
        popup_height = min(460, max(180, 56 + max(1, self._visible_entry_count()) * 28))
        popup.setFixedWidth(popup_width)
        popup.resize(popup_width, popup_height)
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
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
            'QFrame#markingModelPopup { background: #121920; border: 1px solid #31404B; border-radius: 8px; }'
            'QLineEdit { background: #0D1318; color: #E8F0F5; border: 1px solid #354252; border-radius: 5px; padding: 6px 8px; }'
            'QListWidget { background: transparent; color: #E8F0F5; border: 0; padding: 2px; }'
            'QListWidget::item { padding: 6px 8px; border-radius: 4px; }'
            'QListWidget::item:selected { background: #1D3A39; color: #FFFFFF; }'
            'QToolButton { color: #AAB8C5; background: #182129; border: 1px solid #303C48; border-radius: 5px; padding: 5px 8px; }'
            'QToolButton:hover { color: #FFFFFF; border-color: #4A6070; background: #202C36; }'
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


class MarkingSettingsForm(QVBoxLayout):
    model_selected = Signal(bool)
    model_activated = Signal()
    models_refreshed = Signal(list)

    def __init__(self):
        super().__init__()
        basic_settings_form = QFormLayout()
        basic_settings_form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapAllRows)
        basic_settings_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.model_combo_box = MarkingModelComboBox(key='marking_model_id')
        self.model_combo_box.setPlaceholderText('Set marking model directory in "Settings..."')
        self.model_combo_box.activated.connect(self._on_model_activated)
        self.model_combo_box.currentTextChanged.connect(self._on_model_text_changed)
        model_selector = QWidget()
        model_selector_layout = QHBoxLayout(model_selector)
        model_selector_layout.setContentsMargins(0, 0, 0, 0)
        model_selector_layout.setSpacing(4)
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
        QTimer.singleShot(
            _startup_delay_ms('TAGGUI_AUTO_MARKING_STARTUP_DELAY_MS', 6000),
            self.get_local_model_paths,
        )
        settings.change.connect(lambda key, value: self.get_local_model_paths()
            if key == 'marking_models_directory_path' else 0)
        basic_settings_form.addRow('Model', model_selector)
        self.model_warning_label = QLabel()
        self.model_warning_label.setWordWrap(True)
        self.model_warning_label.hide()
        self.model_warning_label.setStyleSheet(
            'color: #F2B84B; padding: 2px 0 4px 0;'
        )
        basic_settings_form.addRow('', self.model_warning_label)

        self.class_table = QTableWidget(0, 3)
        self.class_table.setHorizontalHeaderLabels(
            ['Model class', 'Output label', 'Marking']
        )
        self.class_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.class_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        basic_settings_form.addRow('Classes', self.class_table)
        self.reset_class_labels_button = QPushButton(
            'Reset labels to model defaults'
        )
        self.reset_class_labels_button.setToolTip(
            'Discard custom output labels for the selected model.'
        )
        self.reset_class_labels_button.setEnabled(False)
        basic_settings_form.addRow('', self.reset_class_labels_button)

        self.toggle_advanced_settings_form_button = TallPushButton(
            'Show Advanced Settings')

        self.advanced_settings_form_container = QWidget()
        advanced_settings_form = QFormLayout(
            self.advanced_settings_form_container)
        advanced_settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
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

        self.addLayout(basic_settings_form)
        self.horizontal_line = HorizontalLine()
        self.addWidget(self.horizontal_line)
        self.addWidget(self.toggle_advanced_settings_form_button)
        self.addWidget(self.advanced_settings_form_container)

        self.toggle_advanced_settings_form_button.clicked.connect(
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

    @Slot()
    def toggle_advanced_settings_form(self):
        if self.advanced_settings_form_container.isHidden():
            self.advanced_settings_form_container.show()
            self.toggle_advanced_settings_form_button.setText(
                'Hide Advanced Settings')
        else:
            self.advanced_settings_form_container.hide()
            self.toggle_advanced_settings_form_button.setText(
                'Show Advanced Settings')

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

class AutoMarkings(QDockWidget):
    marking_generated = Signal(QModelIndex, list)
    _CLASS_ACTIONS_SETTINGS_KEY = 'auto_marking_class_actions_json'
    _CLASS_LABELS_SETTINGS_KEY = 'auto_marking_class_labels_json'

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
        # Whether the last block of text in the console text edit should be
        # replaced with the next block of text that is outputted.
        self.replace_last_console_text_edit_block = False
        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('auto_markings')
        self.setWindowTitle('Auto-Markings')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea |
                             Qt.DockWidgetArea.RightDockWidgetArea)

        self.start_cancel_button = TallPushButton('Start Auto-Marking')
        self.start_cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat('%v / %m images marked (%p%)')
        self.progress_bar.hide()
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        self.console_text_edit = QPlainTextEdit()
        set_text_edit_height(self.console_text_edit, 4)
        self.console_text_edit.setReadOnly(True)
        self.console_text_edit.hide()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.start_cancel_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.result_label)
        layout.addWidget(self.console_text_edit)
        self.marking_settings_form = MarkingSettingsForm()
        layout.addLayout(self.marking_settings_form)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(container)
        self.setWidget(scroll_area)

        self.start_cancel_button.clicked.connect(
            self.start_or_cancel_marking)
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
            self.start_cancel_button.setText('Canceling Auto-Marking...')
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
        button_text = ('Cancel Auto-Marking' if is_marking
                       else 'Start Auto-Marking')
        self.start_cancel_button.setText(button_text)

    def _current_model_key(self) -> str:
        return str(self.marking_settings_form.model_combo_box.currentText() or '').strip()

    @staticmethod
    def _load_saved_class_values(key: str) -> dict[str, dict[str, str]]:
        raw = settings.value(key, '{}', type=str)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _save_saved_class_values(
            key: str, payload: dict[str, dict[str, str]]):
        settings.setValue(key, json.dumps(payload))

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
        if self.console_text_edit.isHidden():
            self.console_text_edit.show()
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
                self.result_label.setText(
                    'PT model selected. TagGUI will offer a safer ONNX import '
                    'or explicit unsafe fallback when you run it.'
                )
                self.result_label.show()
                self.start_cancel_button.setEnabled(True)
                return
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
            self.start_cancel_button.setEnabled(False)
            return
        previous = class_table.blockSignals(True)
        try:
            class_table.setRowCount(
                len(self.marking_thread.model.names))
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
                combo.currentTextChanged.connect(
                    lambda _text, self=self: self._persist_class_actions_for_current_model()
                )
                class_table.setCellWidget(row, 2, combo)
        finally:
            class_table.blockSignals(previous)
        self._restore_class_labels_for_current_model()
        self._restore_class_actions_for_current_model()
        self.start_cancel_button.setEnabled(True)
        # NOTE: As this thread has no place to display the output, we keep
        # `stdout` and `stderr`.
        # Redirect `stdout` and `stderr` so that the outputs are displayed in
        # the console text edit.
        ###sys.stdout = self.marking_thread
        ###sys.stderr = self.marking_thread

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
