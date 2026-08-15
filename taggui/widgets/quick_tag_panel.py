"""Compact setup dock for Quick Tag Review."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QStyle,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from widgets.quick_sort_panel import QuickSortKeyButton

from utils.quick_tag import (
    QuickTagMapping,
    QuickTagProfile,
    QuickTagProfileStore,
    QuickTagValidationError,
    builtin_quick_tag_profiles,
    clone_quick_tag_profile,
    default_quick_tag_profile,
    new_quick_tag_id,
    normalize_quick_tag_key,
    reconcile_quick_tag_profiles,
)


_TAG_COLORS = ("#62E7D8", "#7AA2FF", "#F2C96D", "#E87979", "#B98CFF", "#72D49A")


class _QuickTagMappingTable(QTableWidget):
    """Compact shortcut table with a deferred, model-only row move."""

    rows_reordered = Signal()

    def __init__(self, rows=0, columns=4, parent=None):
        super().__init__(rows, columns, parent)
        self._drag_source_row = -1
        self._drag_press_pos = None
        self._manual_dragging = False
        self._reorder_notification_pending = False
        self.setObjectName("quickTagMappingTable")
        # Native QTableWidget DnD can delete the source row when embedded
        # cell widgets are present. Reordering is handled locally instead.
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            self._drag_source_row = index.row() if index.isValid() else -1
            self._drag_press_pos = event.position().toPoint()
            self._manual_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_source_row >= 0
            and self._drag_press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            distance = (event.position().toPoint() - self._drag_press_pos).manhattanLength()
            if not self._manual_dragging and distance >= QApplication.startDragDistance():
                self._manual_dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._manual_dragging:
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._manual_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._move_row_to_position(
                self._drag_source_row,
                event.position().toPoint(),
            )
            self._reset_drag_state()
            event.accept()
            return
        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def _reset_drag_state(self):
        self._drag_source_row = -1
        self._drag_press_pos = None
        self._manual_dragging = False
        self.unsetCursor()

    def _move_row_to_position(self, source: int, position):
        if source < 0 or source >= self.rowCount():
            return
        target_index = self.indexAt(position)
        if target_index.isValid():
            target = target_index.row()
            if position.y() >= self.visualRect(target_index).center().y():
                target += 1
        else:
            target = self.rowCount()
        if target > source:
            target -= 1
        if target == source:
            return
        if self.model().moveRows(QModelIndex(), source, 1, QModelIndex(), target):
            self.setCurrentCell(target, 0)
            self._queue_reorder_notification()

    def _queue_reorder_notification(self):
        if self._reorder_notification_pending:
            return
        self._reorder_notification_pending = True
        QTimer.singleShot(0, self._emit_reorder_notification)

    def _emit_reorder_notification(self):
        self._reorder_notification_pending = False
        self.rows_reordered.emit()


class QuickTagPanel(QDockWidget):
    readiness_changed = Signal(bool)

    SOURCE_OPTIONS = (
        ("Current folder", "current_folder"),
        ("Selected images", "selected"),
        ("Filtered images", "filtered"),
        ("All loaded media", "all_loaded"),
    )

    def __init__(self, main_window):
        super().__init__("Quick Tag Review", main_window)
        self.main_window = main_window
        self.setObjectName("quick_tag_panel")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._build_title_bar()
        self.controller = None
        self.store = QuickTagProfileStore()
        self.profiles: list[QuickTagProfile] = []
        self._builtin_profiles = builtin_quick_tag_profiles()
        self.current_profile_id = ""
        self._loading = False
        self._ready = False
        self._count_key = None
        self._count_value: int | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_profiles)
        self._build_ui()
        self._apply_style()
        self._load_profiles()

    def _build_title_bar(self):
        title_widget = QWidget()
        self._title_widget = title_widget
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(6, 2, 6, 2)
        title_layout.setSpacing(4)
        title = QPushButton("Quick Tag Review")
        title.setObjectName("quickTagDockTitle")
        title.setFlat(True)
        title.setCursor(Qt.CursorShape.ArrowCursor)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        float_button = QPushButton()
        float_button.setObjectName("quickTagDockButton")
        float_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton)
        )
        float_button.setFlat(True)
        float_button.setMaximumSize(16, 16)
        float_button.setToolTip("Float or dock this panel")
        float_button.clicked.connect(lambda: self.setFloating(not self.isFloating()))
        close_button = QPushButton()
        close_button.setObjectName("quickTagDockButton")
        close_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        close_button.setFlat(True)
        close_button.setMaximumSize(16, 16)
        close_button.setToolTip("Close this panel")
        close_button.clicked.connect(self.close)
        title_layout.addWidget(title)
        title_layout.addStretch(1)
        title_layout.addWidget(float_button)
        title_layout.addWidget(close_button)
        self.setTitleBarWidget(title_widget)

    def _build_ui(self):
        root = QWidget(self)
        root.setObjectName("quickTagRoot")
        root.setMinimumSize(0, 0)
        root.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setToolTip(
            "Choose a profile, or edit its name here and press Enter."
        )
        self.profile_combo.setMinimumWidth(0)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.profile_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.profile_combo.setMinimumContentsLength(4)
        self.add_profile_button = QPushButton("+")
        self.copy_profile_button = QPushButton("Copy")
        self.delete_profile_button = QPushButton("×")
        self.add_profile_button.setMinimumWidth(28)
        self.copy_profile_button.setMinimumWidth(48)
        self.delete_profile_button.setMinimumWidth(28)
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.add_profile_button)
        profile_row.addWidget(self.copy_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        layout.addLayout(profile_row)

        source_block = QWidget()
        source_layout = QVBoxLayout(source_block)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(2)
        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        source_label = QLabel("Images")
        self.source_combo = QComboBox()
        for label, value in self.SOURCE_OPTIONS:
            self.source_combo.addItem(label, value)
        self.source_combo.setMinimumWidth(0)
        self.source_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.subfolders_check = QCheckBox("Subfolders")
        self.subfolders_check.setToolTip("Include media in nested folders")
        self.videos_check = QCheckBox("Videos")
        self.videos_check.setToolTip("Include video files")
        for checkbox in (self.subfolders_check, self.videos_check):
            checkbox.setMinimumWidth(52 if checkbox is self.videos_check else 76)
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )
        source_row.addWidget(source_label)
        source_row.addWidget(self.source_combo, 1)
        source_layout.addLayout(source_row)
        source_flags_row = QHBoxLayout()
        source_flags_row.setContentsMargins(0, 0, 0, 0)
        source_flags_row.setSpacing(8)
        source_flags_row.addWidget(self.subfolders_check)
        source_flags_row.addWidget(self.videos_check)
        source_flags_row.addStretch(1)
        source_layout.addLayout(source_flags_row)
        layout.addWidget(source_block)

        mapping_header = QHBoxLayout()
        title = QLabel("TAG SHORTCUTS")
        title.setObjectName("quickTagSectionTitle")
        mapping_header.addWidget(title)
        layout.addLayout(mapping_header)

        self.mapping_table = _QuickTagMappingTable(0, 4)
        self.mapping_table.setToolTip("Drag a shortcut row to reorder it")
        self.mapping_table.setHorizontalHeaderLabels(("Key", "Tag", "Color", ""))
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.mapping_table.setAlternatingRowColors(False)
        self.mapping_table.setMinimumHeight(0)
        self.mapping_table.setMinimumWidth(0)
        self.mapping_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mapping_table.setWordWrap(False)
        self.mapping_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mapping_table.horizontalHeader().setStretchLastSection(False)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.mapping_table.setColumnWidth(0, 58)
        self.mapping_table.setColumnWidth(2, 34)
        self.mapping_table.setColumnWidth(3, 34)
        self.mapping_table.itemChanged.connect(lambda *_: self._schedule_save())
        self.mapping_table.rows_reordered.connect(self._schedule_save)
        layout.addWidget(self.mapping_table, 1)

        mapping_buttons = QHBoxLayout()
        self.add_mapping_button = QPushButton("＋ Add tag shortcut")
        self.sort_mapping_button = QPushButton("A–Z")
        self.remove_mapping_button = QPushButton("Remove")
        self.add_mapping_button.setMinimumWidth(104)
        self.sort_mapping_button.setMinimumWidth(48)
        self.sort_mapping_button.setToolTip(
            "Reorder tag shortcuts alphabetically (your order is otherwise preserved)"
        )
        self.remove_mapping_button.setMinimumWidth(64)
        mapping_buttons.addWidget(self.add_mapping_button)
        mapping_buttons.addWidget(self.sort_mapping_button)
        mapping_buttons.addStretch(1)
        mapping_buttons.addWidget(self.remove_mapping_button)
        layout.addLayout(mapping_buttons)

        controls_toggle = QToolButton()
        controls_toggle.setText("Keyboard controls")
        controls_toggle.setCheckable(True)
        controls_toggle.setChecked(False)
        controls_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        controls_toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(controls_toggle)
        self.controls_frame = QWidget()
        controls_form = QFormLayout(self.controls_frame)
        self.refine_edit = QLineEdit("Tab")
        self.insert_edit = QLineEdit("Shift+Tab")
        self.remove_edit = QLineEdit("Backspace")
        self.advance_edit = QLineEdit("Space")
        controls_form.addRow("Refine previous", self.refine_edit)
        controls_form.addRow("Insert tag", self.insert_edit)
        controls_form.addRow("Remove tag", self.remove_edit)
        controls_form.addRow("Save / next", self.advance_edit)
        self.controls_frame.hide()
        layout.addWidget(self.controls_frame)
        controls_toggle.toggled.connect(lambda checked: (controls_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow), self.controls_frame.setVisible(checked)))

        self.fullscreen_check = QCheckBox("Start in fullscreen")
        layout.addWidget(self.fullscreen_check)
        self.summary_label = QLabel("Add at least one tag shortcut")
        self.summary_label.setObjectName("quickSortRunSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.start_button = QPushButton("Start Quick Tag Review")
        self.start_button.setObjectName("quickSortRunButton")
        layout.addWidget(self.start_button)
        self.setWidget(root)

        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.profile_combo.lineEdit().editingFinished.connect(self._rename_profile)
        self.add_profile_button.clicked.connect(self._add_profile)
        self.copy_profile_button.clicked.connect(self._copy_profile)
        self.delete_profile_button.clicked.connect(self._delete_profile)
        self.add_mapping_button.clicked.connect(self._add_mapping)
        self.sort_mapping_button.clicked.connect(self._sort_mappings_alphabetically)
        self.remove_mapping_button.clicked.connect(self._remove_mapping)
        self.source_combo.currentIndexChanged.connect(self._schedule_save)
        for widget in (self.subfolders_check, self.videos_check, self.fullscreen_check):
            widget.toggled.connect(self._schedule_save)
        for widget in (self.refine_edit, self.insert_edit, self.remove_edit, self.advance_edit):
            widget.textChanged.connect(self._schedule_save)
        self.start_button.clicked.connect(self.start_quick_tag)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget { font-size: 11px; }
            QWidget#quickTagRoot, QTableWidget { background: #303030; }
            QLabel#quickTagSectionTitle { color: #E0E0E0; font-weight: 700; }
            QLabel#quickTagMutedLabel { color: #9E9E9E; font-size: 10px; }
            QPushButton#quickTagDockTitle {
                padding: 0 2px;
                border: none;
                background: transparent;
                color: #E0E0E0;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 14px;
                font-weight: 700;
                min-height: 20px;
                text-align: left;
            }
            QPushButton#quickTagDockTitle:hover { background: transparent; }
            QPushButton#quickTagDockButton {
                padding: 0;
                border: none;
                background: transparent;
                max-width: 16px;
                max-height: 16px;
            }
            QPushButton#quickTagDockButton:hover { background: #303030; }
            QTableWidget { border: 1px solid #4A4A4A; gridline-color: #4A4A4A; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #3B4F66; }
            QLineEdit, QComboBox { color: #E8E8E8; background: #242424; border: 1px solid #4A4A4A; border-radius: 6px; padding: 4px 7px; min-height: 22px; }
            QLineEdit:focus, QComboBox:focus { border-color: #7AA2FF; }
            QPushButton { color: #E0E0E0; background: #3A3A3A; border: 1px solid #4A4A4A; border-radius: 6px; padding: 4px 8px; }
            QPushButton:hover { background: #4A4A4A; border-color: #5A5A5A; }
            QToolButton { color: #E0E0E0; background: #3A3A3A; border: 1px solid #4A4A4A; border-radius: 6px; padding: 4px 8px; }
            QToolButton:hover { background: #4A4A4A; border-color: #5A5A5A; }
            QPushButton#quickTagKeyButton { color: #E8E8E8; background: #3A3A3A; border: 1px solid #5A5A5A; border-radius: 5px; padding: 3px 6px; font-weight: 700; }
            QPushButton#quickTagKeyButton:hover { background: #4A4A4A; border-color: #7AA2FF; }
            QPushButton#quickTagKeyButton[capturing="true"] { color: #101010; background: #62E7D8; border-color: #62E7D8; }
            QLabel#quickSortRunSummary { color: #BDBDBD; }
            QPushButton#quickSortRunButton { color: #FFFFFF; background: #3B82F6; border: 0; border-radius: 6px; padding: 9px 12px; font-weight: 900; }
            QPushButton#quickSortRunButton:hover { background: #4F8EF7; }
            QPushButton#quickSortRunButton:disabled { color: #777777; background: #353535; }
        """)

    def bind_controller(self, controller):
        self.controller = controller
        controller.active_changed.connect(self._controller_active_changed)
        self._refresh_readiness()

    def _controller_active_changed(self, active: bool):
        self.start_button.setText("Quick Tag Running" if active else "Start Quick Tag Review")
        self.start_button.setEnabled(not active and self.is_ready)

    def _current_profile(self) -> QuickTagProfile | None:
        return next((profile for profile in self.profiles if profile.id == self.current_profile_id), None)

    def _load_profiles(self):
        try:
            self.profiles = self.store.load()
        except QuickTagValidationError:
            self.profiles = []
        self.profiles, migrated = reconcile_quick_tag_profiles(
            self.profiles,
            self._builtin_profiles,
        )
        if migrated:
            try:
                self.store.save(self.profiles)
            except (OSError, QuickTagValidationError):
                pass
        if not self.profiles:
            self.profiles = [default_quick_tag_profile()]
            try:
                self.store.save(self.profiles)
            except (OSError, QuickTagValidationError):
                pass
        selected = self.profiles[0]
        self._rebuild_profile_combo(selected.id)
        self._load_profile(selected)

    def _add_preset(self, template: QuickTagProfile, *, committed: bool = False):
        if not committed and (self._commit(validate=True) is None or not self._save_profiles()):
            return
        existing = next(
            (item for item in self.profiles if item.template_key == template.template_key),
            None,
        )
        if existing is not None:
            self._rebuild_profile_combo(existing.id)
            self._load_profile(existing)
            return
        profile = clone_quick_tag_profile(template, name=f"{template.name} (custom)")
        self.profiles.append(profile)
        self._rebuild_profile_combo(profile.id)
        self._load_profile(profile)
        self._save_profiles()

    def _rebuild_profile_combo(self, selected_id: str):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for preset in self._builtin_profiles:
            index = self.profile_combo.count()
            self.profile_combo.addItem(f"Preset: {preset.name}", f"__builtin__:{preset.id}")
            self.profile_combo.setItemData(
                index,
                "Built-in template — selecting it creates an editable profile.",
                Qt.ItemDataRole.ToolTipRole,
            )
            self.profile_combo.setItemData(
                index, QColor("#62E7D8"), Qt.ItemDataRole.ForegroundRole
            )
            self.profile_combo.setItemData(
                index, QColor("#26383B"), Qt.ItemDataRole.BackgroundRole
            )
        if self._builtin_profiles and self.profiles:
            separator_index = self.profile_combo.count()
            self.profile_combo.insertSeparator(separator_index)
            separator_item = self.profile_combo.model().item(separator_index)
            if separator_item is not None:
                separator_item.setFlags(separator_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        for profile in self.profiles:
            self.profile_combo.addItem(profile.name, profile.id)
        index = self.profile_combo.findData(selected_id)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def _load_profile(self, profile: QuickTagProfile):
        self._loading = True
        try:
            self.current_profile_id = profile.id
            self.profile_combo.setEditText(profile.name)
            self._set_combo_data(self.source_combo, profile.source_scope)
            self.subfolders_check.setChecked(profile.include_subfolders)
            self.videos_check.setChecked(profile.include_videos)
            self.refine_edit.setText(profile.refine_key)
            self.insert_edit.setText(profile.insert_key)
            self.remove_edit.setText(profile.remove_key)
            self.advance_edit.setText(profile.advance_key)
            self.fullscreen_check.setChecked(profile.start_fullscreen)
            self._populate_table(profile.mappings)
        finally:
            self._loading = False
        self._refresh_readiness()

    @staticmethod
    def _set_combo_data(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _populate_table(self, mappings: list[QuickTagMapping]):
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(0)
        for mapping in mappings:
            self._insert_row(mapping)
        self.mapping_table.blockSignals(False)

    def _insert_row(self, mapping: QuickTagMapping):
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        key_button = QuickSortKeyButton(mapping.key)
        key_button.setObjectName("quickTagKeyButton")
        key_button.setFixedWidth(52)
        key_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        key_button.setToolTip("Click, then press the key for this tag")
        key_button.key_changed.connect(self._schedule_save)
        self.mapping_table.setCellWidget(row, 0, key_button)
        tag_item = QTableWidgetItem(mapping.tag)
        tag_item.setData(Qt.ItemDataRole.UserRole, mapping.id)
        self.mapping_table.setItem(row, 1, tag_item)
        color_button = QPushButton()
        color_button.setObjectName("quickTagColorButton")
        color_button.setFixedSize(26, 24)
        color_button.setProperty("quick_tag_color", mapping.color)
        self._refresh_color_button(color_button)
        color_button.clicked.connect(
            lambda _checked=False, button=color_button: self._choose_color(button)
        )
        self.mapping_table.setCellWidget(row, 2, color_button)
        remove = QPushButton("X")
        remove.setObjectName("quickTagRemoveButton")
        remove.setFixedSize(26, 24)
        remove.setToolTip("Remove this tag shortcut")
        remove.clicked.connect(
            lambda _checked=False, target=mapping.id: self._remove_row_by_id(target)
        )
        self.mapping_table.setCellWidget(row, 3, remove)

    def _sort_mappings_alphabetically(self):
        """Apply an explicit A–Z order without changing shortcut assignments."""
        mappings: list[QuickTagMapping] = []
        for row in range(self.mapping_table.rowCount()):
            key_button = self.mapping_table.cellWidget(row, 0)
            tag_item = self.mapping_table.item(row, 1)
            color_button = self.mapping_table.cellWidget(row, 2)
            if tag_item is None:
                continue
            mappings.append(
                QuickTagMapping(
                    id=str(tag_item.data(Qt.ItemDataRole.UserRole) or new_quick_tag_id("tag")),
                    key=key_button.key if isinstance(key_button, QuickSortKeyButton) else "",
                    tag=tag_item.text().strip(),
                    color=str(
                        color_button.property("quick_tag_color")
                        if isinstance(color_button, QPushButton)
                        else "#62E7D8"
                    ),
                )
            )
        mappings.sort(key=lambda mapping: mapping.tag.casefold())
        self._populate_table(mappings)
        self._schedule_save()

    @staticmethod
    def _refresh_color_button(button: QPushButton):
        color = QColor(str(button.property("quick_tag_color") or "#62E7D8"))
        if not color.isValid():
            color = QColor("#62E7D8")
            button.setProperty("quick_tag_color", color.name())
        button.setToolTip(f"Choose accent color ({color.name()})")
        button.setStyleSheet(
            f"QPushButton {{ background: {color.name()}; border: 1px solid #D8D8D8; border-radius: 5px; }}"
            "QPushButton:hover { border: 2px solid #FFFFFF; }"
        )

    def _choose_color(self, button: QPushButton):
        current = QColor(str(button.property("quick_tag_color") or "#62E7D8"))
        selected = QColorDialog.getColor(current, self, "Choose tag color")
        if not selected.isValid():
            return
        button.setProperty("quick_tag_color", selected.name())
        self._refresh_color_button(button)
        self._schedule_save()

    def _profile_from_ui(self) -> QuickTagProfile:
        current = self._current_profile()
        if current is None:
            raise QuickTagValidationError("No Quick Tag profile is selected.")
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            key_button = self.mapping_table.cellWidget(row, 0)
            key = key_button.key if isinstance(key_button, QuickSortKeyButton) else ""
            tag_item = self.mapping_table.item(row, 1)
            if tag_item is None:
                continue
            color_button = self.mapping_table.cellWidget(row, 2)
            color = str(
                color_button.property("quick_tag_color")
                if isinstance(color_button, QPushButton)
                else "#62E7D8"
            )
            mapping_id = str(tag_item.data(Qt.ItemDataRole.UserRole) or new_quick_tag_id("tag"))
            mappings.append(QuickTagMapping(id=mapping_id, key=key, tag=tag_item.text(), color=color))
        profile = QuickTagProfile(
            id=current.id,
            # currentIndexChanged fires after the combo's visible text has
            # already changed. Keep the old profile name while committing its
            # draft; the rename handler owns deliberate name edits.
            name=current.name,
            mappings=mappings,
            source_scope=str(self.source_combo.currentData() or "current_folder"),
            include_subfolders=self.subfolders_check.isChecked(),
            include_videos=self.videos_check.isChecked(),
            start_fullscreen=self.fullscreen_check.isChecked(),
            refine_key=self.refine_edit.text(),
            insert_key=self.insert_edit.text(),
            remove_key=self.remove_edit.text(),
            advance_key=self.advance_edit.text(),
            template_key=current.template_key,
        )
        profile.validate()
        return profile

    def _commit(self, validate: bool = False) -> QuickTagProfile | None:
        if self._loading:
            return None
        try:
            profile = self._profile_from_ui()
        except QuickTagValidationError as exc:
            if validate:
                QMessageBox.warning(self, "Quick Tags", str(exc))
            self.summary_label.setText(str(exc))
            return None
        for index, existing in enumerate(self.profiles):
            if existing.id == profile.id:
                self.profiles[index] = profile
                break
        self.current_profile_id = profile.id
        return profile

    def _save_profiles(self):
        profile = self._commit()
        if profile is None:
            return False
        try:
            self.store.save(self.profiles)
        except (OSError, QuickTagValidationError) as exc:
            self.summary_label.setText(str(exc))
            return False
        self._refresh_readiness()
        return True

    def _schedule_save(self, *_args):
        if not self._loading:
            self._save_timer.start()
            self._refresh_readiness()

    def _profile_changed(self, index: int):
        if self._loading or index < 0:
            return
        if self._commit(validate=True) is None or not self._save_profiles():
            self._rebuild_profile_combo(self.current_profile_id)
            return
        profile_id = str(self.profile_combo.itemData(index) or "")
        if profile_id.startswith("__builtin__:"):
            preset_id = profile_id.split(":", 1)[1]
            preset = next((item for item in self._builtin_profiles if item.id == preset_id), None)
            if preset is not None:
                self._add_preset(preset, committed=True)
            return
        profile = next((item for item in self.profiles if item.id == profile_id), None)
        if profile is not None:
            self._load_profile(profile)

    def _rename_profile(self):
        if self._loading:
            return
        profile = self._current_profile()
        if profile is None:
            return
        name = self.profile_combo.currentText().strip()
        if not name:
            self.profile_combo.setEditText(profile.name)
            return
        if name == profile.name:
            return
        profile.name = name
        index = self.profile_combo.findData(profile.id)
        if index >= 0:
            self.profile_combo.setItemText(index, name)
            self.profile_combo.setCurrentIndex(index)
            self.profile_combo.setEditText(name)
        self._schedule_save()

    def _add_profile(self):
        name, accepted = QInputDialog.getText(self, "New Quick Tag profile", "Profile name:", text="New Quick Tags")
        if not accepted or not name.strip():
            return
        if self._commit(validate=True) is None:
            return
        profile = default_quick_tag_profile(name.strip())
        self.profiles.append(profile)
        self._rebuild_profile_combo(profile.id)
        self._load_profile(profile)
        self._save_profiles()

    def _copy_profile(self):
        current = self._commit(validate=True)
        if current is None:
            return
        duplicate = deepcopy(current)
        duplicate.id = new_quick_tag_id("profile")
        duplicate.name = f"{current.name} Copy"
        for mapping in duplicate.mappings:
            mapping.id = new_quick_tag_id("tag")
        self.profiles.append(duplicate)
        self._rebuild_profile_combo(duplicate.id)
        self._load_profile(duplicate)
        self._save_profiles()

    def _delete_profile(self):
        if len(self.profiles) <= 1:
            return
        current = self._current_profile()
        if current is None:
            return
        if QMessageBox.question(self, "Quick Tags", f"Delete {current.name!r}?") != QMessageBox.StandardButton.Yes:
            return
        self.profiles = [profile for profile in self.profiles if profile.id != current.id]
        self._rebuild_profile_combo(self.profiles[0].id)
        self._load_profile(self.profiles[0])
        self._save_profiles()

    def _add_mapping(self):
        number = self.mapping_table.rowCount() + 1
        used = {
            self.mapping_table.cellWidget(row, 0).key.casefold()
            for row in range(self.mapping_table.rowCount())
            if isinstance(self.mapping_table.cellWidget(row, 0), QuickSortKeyButton)
        }
        key = next((candidate for candidate in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if candidate.casefold() not in used), "F1")
        color = _TAG_COLORS[(number - 1) % len(_TAG_COLORS)]
        self._insert_row(QuickTagMapping(tag=f"tag {number}", key=key, color=color))
        self._schedule_save()

    def _remove_row_by_id(self, mapping_id: str):
        for row in range(self.mapping_table.rowCount()):
            item = self.mapping_table.item(row, 1)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == mapping_id:
                self.mapping_table.removeRow(row)
                self._schedule_save()
                return

    def _remove_mapping(self):
        row = self.mapping_table.currentRow()
        if row >= 0:
            self.mapping_table.removeRow(row)
            self._schedule_save()

    @property
    def is_ready(self) -> bool:
        return bool(self._ready)

    def _refresh_readiness(self):
        if self.controller is None or self.controller.active:
            self._ready = False
            self.start_button.setEnabled(False)
            self.summary_label.setText("Quick Tags is still connecting to the browser.")
            self.readiness_changed.emit(False)
            return
        try:
            profile = self._profile_from_ui()
            if not profile.enabled_mappings():
                raise QuickTagValidationError("Add at least one tag shortcut")
            context = self.controller.sort_controller.resolve_browser_context()
            model = context.get("model")
            directory = getattr(model, "_directory_path", None)
            if directory is None:
                raise QuickTagValidationError("Load a folder to prepare a Quick Tag queue.")
            count_key = (
                profile.source_scope,
                bool(profile.include_subfolders),
                bool(profile.include_videos),
                id(model),
                str(directory),
                str(getattr(model, "_filter_sql", "") or ""),
                repr(tuple(getattr(model, "_filter_bindings", ()) or ())),
            )
            if count_key != self._count_key:
                self._count_key = count_key
                self._count_value = int(self.controller.estimate_queue_count(profile, context))
            count = int(self._count_value or 0)
            scope_labels = {
                "current_folder": "from this folder",
                "selected": "selected",
                "filtered": "matching the current filter",
                "all_loaded": "across all loaded folders",
            }
            self.summary_label.setText(
                f"{count:,} media {scope_labels.get(profile.source_scope, '')}"
            )
            self.start_button.setText(f"Start with {count:,} media")
            ready = count > 0
        except Exception as exc:
            self.summary_label.setText(str(exc))
            self.start_button.setText("Start Quick Tag Review")
            ready = False
        self._ready = bool(ready)
        self.start_button.setEnabled(ready)
        self.readiness_changed.emit(self._ready)

    def start_quick_tag(self):
        profile = self._commit(validate=True)
        if profile is None or not self._save_profiles() or self.controller is None:
            return False
        return self.controller.start_session(profile)
