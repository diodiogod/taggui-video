"""Compact modeless text replace/swap utility."""

from __future__ import annotations

import json
import re

from PySide6.QtCore import QPoint, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout,
    QWidget,
)

from models.image_list_model import Scope
from utils.settings import settings
from utils.text_transform import TextTransformOptions, transform_text


BUILTIN_PRESETS = {
    "Left ↔ Right": ("left", "right", True),
    "His ↔ Her": ("his", "her", True),
    "Man ↔ Woman": ("man", "woman", True),
    "Foreground ↔ Background": ("foreground", "background", True),
    "Day ↔ Night": ("day", "night", True),
}


class TextTransformTool(QDialog):
    """A non-dockable tool window associated with the main TagGUI window."""

    SCOPES = (
        "Selected text",
        "Selected caption rows",
        "Current media caption",
        "Selected media",
        "Filtered media",
        "All media",
    )

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool)
        self.main_window = parent
        self.setWindowTitle("Text Transform")
        self.setModal(False)
        self.setMinimumWidth(390)
        self.setMaximumHeight(260)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Custom")
        self.preset_combo.addItems(BUILTIN_PRESETS)
        self._load_user_presets()
        self.preset_combo.currentTextChanged.connect(self._preset_selected)
        preset_row.addWidget(self.preset_combo, 1)
        self.preset_menu_button = QToolButton()
        self.preset_menu_button.setText("⋯")
        self.preset_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._rebuild_preset_menu()
        preset_row.addWidget(self.preset_menu_button)
        root.addLayout(preset_row)

        words = QHBoxLayout()
        self.first_edit = QLineEdit()
        self.first_edit.setPlaceholderText("Find A")
        self.direction_button = QPushButton("⇄")
        self.direction_button.setCheckable(True)
        self.direction_button.setChecked(True)
        self.direction_button.setFixedWidth(38)
        self.direction_button.setToolTip("Checked: swap A ↔ B; unchecked: replace A → B")
        self.direction_button.toggled.connect(self._sync_mode_label)
        self.second_edit = QLineEdit()
        self.second_edit.setPlaceholderText("Find/replace B")
        words.addWidget(self.first_edit, 1)
        words.addWidget(self.direction_button)
        words.addWidget(self.second_edit, 1)
        root.addLayout(words)

        action_row = QHBoxLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(self.SCOPES)
        action_row.addWidget(self.scope_combo, 1)
        self.advanced_button = QToolButton()
        self.advanced_button.setText("Options ▾")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._set_advanced_visible)
        action_row.addWidget(self.advanced_button)
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.preview)
        action_row.addWidget(self.preview_button)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.apply)
        action_row.addWidget(self.apply_button)
        root.addLayout(action_row)

        self.advanced_widget = QWidget()
        advanced = QFormLayout(self.advanced_widget)
        advanced.setContentsMargins(0, 2, 0, 0)
        checks = QHBoxLayout()
        self.whole_words_check = QCheckBox("Whole words")
        self.preserve_case_check = QCheckBox("Preserve capitalization")
        self.match_case_check = QCheckBox("Match case")
        self.regex_check = QCheckBox("Regex")
        for check in (
            self.whole_words_check, self.preserve_case_check,
            self.match_case_check, self.regex_check,
        ):
            checks.addWidget(check)
        advanced.addRow(checks)
        self.advanced_widget.hide()
        root.addWidget(self.advanced_widget)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self._restore_state()
        self.first_edit.textChanged.connect(self._mark_custom)
        self.second_edit.textChanged.connect(self._mark_custom)
        self.direction_button.toggled.connect(self._mark_custom)

    def _user_presets(self) -> dict:
        raw = settings.value("text_transform_user_presets", "{}", type=str)
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def _load_user_presets(self):
        for name in self._user_presets():
            if name not in BUILTIN_PRESETS:
                self.preset_combo.addItem(name)

    def _rebuild_preset_menu(self):
        menu = QMenu(self.preset_menu_button)
        menu.addAction("Save Current as Preset…", self._save_preset)
        menu.addAction("Delete Current Preset", self._delete_preset)
        self.preset_menu_button.setMenu(menu)

    def _save_preset(self):
        from PySide6.QtWidgets import QInputDialog
        name, accepted = QInputDialog.getText(self, "Save Preset", "Preset name")
        name = name.strip()
        if not accepted or not name:
            return
        presets = self._user_presets()
        presets[name] = [self.first_edit.text(), self.second_edit.text(), self.direction_button.isChecked()]
        settings.setValue("text_transform_user_presets", json.dumps(presets))
        if self.preset_combo.findText(name) < 0:
            self.preset_combo.addItem(name)
        self.preset_combo.setCurrentText(name)

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        presets = self._user_presets()
        if name not in presets:
            return
        presets.pop(name)
        settings.setValue("text_transform_user_presets", json.dumps(presets))
        index = self.preset_combo.findText(name)
        if index >= 0:
            self.preset_combo.removeItem(index)
        self.preset_combo.setCurrentIndex(0)

    def _preset_selected(self, name: str):
        value = BUILTIN_PRESETS.get(name) or self._user_presets().get(name)
        if not value:
            return
        for widget in (self.first_edit, self.second_edit, self.direction_button):
            widget.blockSignals(True)
        self.first_edit.setText(value[0])
        self.second_edit.setText(value[1])
        self.direction_button.setChecked(bool(value[2]))
        for widget in (self.first_edit, self.second_edit, self.direction_button):
            widget.blockSignals(False)
        self._sync_mode_label()

    def _mark_custom(self, *_args):
        if self.preset_combo.currentText() != "Custom":
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(0)
            self.preset_combo.blockSignals(False)

    def _sync_mode_label(self, *_args):
        self.direction_button.setText("⇄" if self.direction_button.isChecked() else "→")

    def _set_advanced_visible(self, visible: bool):
        self.advanced_widget.setVisible(visible)
        self.advanced_button.setText("Options ▴" if visible else "Options ▾")
        self.adjustSize()

    def _options(self) -> TextTransformOptions:
        return TextTransformOptions(
            first=self.first_edit.text(),
            second=self.second_edit.text(),
            swap=self.direction_button.isChecked(),
            whole_words=self.whole_words_check.isChecked(),
            match_case=self.match_case_check.isChecked(),
            preserve_case=self.preserve_case_check.isChecked(),
            use_regex=self.regex_check.isChecked(),
        )

    def capture_editor_selection(self):
        editor = self.main_window.image_tags_editor
        selected = editor.selected_descriptive_text()
        if selected:
            self.first_edit.setText(selected)
            self.scope_combo.setCurrentText("Selected text")

    def _validate(self) -> bool:
        options = self._options()
        if not options.first or (options.swap and not options.second):
            self.status_label.setText("Enter both values for swapping, or A for replacement.")
            return False
        try:
            transform_text("", options)
        except re.error as error:
            self.status_label.setText(f"Invalid regular expression: {error}")
            return False
        return True

    @Slot()
    def preview(self):
        if not self._validate():
            return
        try:
            captions, replacements = self._run(preview=True)
        except (ValueError, re.error) as error:
            self.status_label.setText(str(error))
            return
        self.status_label.setText(
            f"Preview: {replacements:,} replacement(s) in {captions:,} caption(s)."
        )

    @Slot()
    def apply(self):
        if not self._validate():
            return
        scope = self.scope_combo.currentText()
        if scope in ("Selected media", "Filtered media", "All media"):
            captions, replacements = self._run(preview=True)
            if not replacements:
                self.status_label.setText("No matches found.")
                return
            reply = QMessageBox.question(
                self,
                "Apply Text Transform",
                f"Apply {replacements:,} replacement(s) to {captions:,} caption(s)?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            captions, replacements = self._run(preview=False)
        except (ValueError, re.error) as error:
            self.status_label.setText(str(error))
            return
        self.status_label.setText(
            f"Applied {replacements:,} replacement(s) to {captions:,} caption(s)."
        )
        self._save_state()

    def _run(self, *, preview: bool) -> tuple[int, int]:
        scope = self.scope_combo.currentText()
        options = self._options()
        if scope in ("Selected text", "Selected caption rows", "Current media caption"):
            return self.main_window.image_tags_editor.apply_text_transform(
                scope, options, preview=preview
            )
        model_scope = {
            "Selected media": Scope.SELECTED_IMAGES,
            "Filtered media": Scope.FILTERED_IMAGES,
            "All media": Scope.ALL_IMAGES,
        }[scope]
        model = self.main_window.image_list_model
        if preview:
            return model.count_text_transform(options, model_scope)
        return model.apply_text_transform(options, model_scope)

    def apply_last(self):
        self.apply()

    def _restore_state(self):
        self.first_edit.setText(settings.value("text_transform_first", "left", type=str))
        self.second_edit.setText(settings.value("text_transform_second", "right", type=str))
        self.direction_button.setChecked(settings.value("text_transform_swap", True, type=bool))
        self.scope_combo.setCurrentText(settings.value("text_transform_scope", "Selected text", type=str))
        self.whole_words_check.setChecked(settings.value("text_transform_whole_words", True, type=bool))
        self.preserve_case_check.setChecked(settings.value("text_transform_preserve_case", True, type=bool))
        self.match_case_check.setChecked(settings.value("text_transform_match_case", False, type=bool))
        self.regex_check.setChecked(settings.value("text_transform_regex", False, type=bool))
        position = settings.value("text_transform_position", None)
        if isinstance(position, QPoint):
            self.move(position)
        self._sync_mode_label()

    def _save_state(self):
        settings.setValue("text_transform_first", self.first_edit.text())
        settings.setValue("text_transform_second", self.second_edit.text())
        settings.setValue("text_transform_swap", self.direction_button.isChecked())
        settings.setValue("text_transform_scope", self.scope_combo.currentText())
        settings.setValue("text_transform_whole_words", self.whole_words_check.isChecked())
        settings.setValue("text_transform_preserve_case", self.preserve_case_check.isChecked())
        settings.setValue("text_transform_match_case", self.match_case_check.isChecked())
        settings.setValue("text_transform_regex", self.regex_check.isChecked())
        settings.setValue("text_transform_position", self.pos())

    def closeEvent(self, event: QCloseEvent):
        self._save_state()
        event.accept()

    def reject(self):
        """Let Escape hide the tool without destroying its configuration."""
        self._save_state()
        self.hide()
