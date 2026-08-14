"""Modern dockable configuration panel for Quick Sort."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.quick_sort import (
    QuickSortMapping,
    QuickSortProfile,
    QuickSortProfileStore,
    QuickSortValidationError,
    default_quick_sort_profile,
    new_quick_sort_id,
    normalize_key_sequence,
)
from utils.settings import settings


_MAPPING_COLOR_PALETTE = (
    "#4C9AFF",
    "#FF8A65",
    "#AB47BC",
    "#66BB6A",
    "#FFD54F",
    "#26C6DA",
    "#EC407A",
    "#7E57C2",
    "#9CCC65",
    "#FFA726",
    "#42A5F5",
    "#D4E157",
)


class _CompressibleQuickSortRoot(QWidget):
    def minimumSizeHint(self):
        return QSize(0, 0)


class _CompressibleQuickSortScroll(QScrollArea):
    def minimumSizeHint(self):
        return QSize(0, 0)


class _CompressibleQuickSortCombo(QComboBox):
    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())


class QuickSortKeyButton(QPushButton):
    """Push button that captures one portable Qt key sequence."""

    key_changed = Signal(str)

    def __init__(self, key: str = "", parent=None):
        super().__init__(parent)
        self._key = normalize_key_sequence(key)
        self._capturing = False
        self.setObjectName("quickSortKeyButton")
        self.setMinimumWidth(64)
        self.clicked.connect(self.begin_capture)
        self._refresh_text()

    @property
    def key(self) -> str:
        return self._key

    def set_key(self, key: str):
        self._key = normalize_key_sequence(key)
        self._refresh_text()

    def _refresh_text(self):
        self.setText(self._key or "Set key")
        self.setToolTip(
            "Click, then press the keyboard key used for this Quick Sort choice."
        )

    def begin_capture(self):
        self._capturing = True
        self.setText("Press key…")
        self.setProperty("capturing", True)
        self.style().unpolish(self)
        self.style().polish(self)
        app = QApplication.instance()
        if app is not None:
            app.setProperty("quick_sort_key_capture", True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def _end_capture(self):
        if not self._capturing:
            return
        self._capturing = False
        try:
            self.releaseKeyboard()
        except RuntimeError:
            pass
        app = QApplication.instance()
        if app is not None:
            app.setProperty("quick_sort_key_capture", False)
        self.setProperty("capturing", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_text()

    def event(self, event):
        if self._capturing and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._end_capture()
            event.accept()
            return
        if event.key() in {
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }:
            event.accept()
            return
        sequence = normalize_key_sequence(
            QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText
            )
        )
        if sequence:
            self._key = sequence
            self.key_changed.emit(sequence)
        self._end_capture()
        event.accept()

    def focusOutEvent(self, event):
        self._end_capture()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self._end_capture()
        super().hideEvent(event)


class QuickSortMappingCard(QFrame):
    changed = Signal()
    remove_requested = Signal(str)

    def __init__(self, mapping: QuickSortMapping, *, kind: str, parent=None):
        super().__init__(parent)
        self.mapping_id = mapping.id
        self.kind = kind
        self.color = mapping.color
        self.setObjectName("quickSortMappingCard")
        self.setProperty("accent", self.color)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 3, 4, 3)
        root.setSpacing(5)
        self.enabled_check = QCheckBox()
        self.enabled_check.setChecked(mapping.enabled)
        self.enabled_check.setToolTip(f"Enable this {kind}")
        self.key_button = QuickSortKeyButton(mapping.key)
        self.key_button.setFixedWidth(52)
        self.key_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        # Folder is canonical for legacy profiles because changing it during
        # migration would silently redirect files. The one practical value is
        # now used both as the on-screen label and actual relative folder.
        destination = str(mapping.folder or mapping.name or "").strip()
        self.destination_edit = QLineEdit(destination)
        self.destination_edit.setPlaceholderText(
            "Destination" if kind == "destination" else kind.title()
        )
        self.destination_edit.setToolTip(
            "Used both for feedback and as the relative destination folder. "
            "Nested folders such as People/Heads are allowed."
        )
        self.destination_edit.setMinimumWidth(0)
        self.destination_edit.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.color_button = QPushButton()
        self.color_button.setObjectName("quickSortColorButton")
        self.color_button.setFixedSize(20, 20)
        self.color_button.setToolTip("Choose an accent color")
        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("quickSortRemoveButton")
        self.remove_button.setFixedSize(22, 22)
        self.remove_button.setToolTip(f"Remove this {kind}")
        root.addWidget(self.enabled_check)
        root.addWidget(self.key_button)
        root.addWidget(self.destination_edit, 1)
        root.addWidget(self.color_button)
        root.addWidget(self.remove_button)

        self.enabled_check.toggled.connect(self.changed)
        self.key_button.key_changed.connect(lambda _key: self.changed.emit())
        self.destination_edit.textChanged.connect(self.changed)
        self.color_button.clicked.connect(self._choose_color)
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.mapping_id)
        )
        self._refresh_accent()

    def _choose_color(self):
        chosen = QColorDialog.getColor(QColor(self.color), self, "Mapping color")
        if not chosen.isValid():
            return
        self.color = chosen.name()
        self._refresh_accent()
        self.changed.emit()

    def _refresh_accent(self):
        color = QColor(self.color)
        if not color.isValid():
            color = QColor("#62E7D8")
        self.color = color.name()
        self.color_button.setStyleSheet(
            f"background: {self.color}; border: 1px solid #707070; border-radius: 4px;"
        )

    def mapping(self) -> QuickSortMapping:
        destination = self.destination_edit.text().strip()
        return QuickSortMapping(
            id=self.mapping_id,
            name=destination,
            key=self.key_button.key,
            folder=destination,
            color=self.color,
            enabled=self.enabled_check.isChecked(),
        )


class QuickSortPanel(QDockWidget):
    """Profile-driven Quick Sort setup and launch dock."""

    start_requested = Signal(object)
    readiness_changed = Signal(bool)

    SOURCE_OPTIONS = (
        ("Current folder", "current_folder"),
        ("Selected media", "selected"),
        ("Filtered results", "filtered"),
        ("All loaded media", "all_loaded"),
    )
    OPERATION_OPTIONS = (
        ("Move originals into destination folders", "move"),
        ("Copy originals and keep source files", "copy"),
    )
    COLLISION_OPTIONS = (
        ("Add a number to the new filename", "append"),
        ("Leave the file unsorted", "skip"),
        ("Ask before each conflict", "ask"),
    )

    def __init__(self, main_window):
        super().__init__("Quick Sort", main_window)
        self.main_window = main_window
        self.controller = None
        self.setObjectName("quick_sort_panel")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setMinimumWidth(0)
        self.store = QuickSortProfileStore()
        self.profiles: list[QuickSortProfile] = []
        self.current_profile_id: str | None = None
        self.destination_cards: list[QuickSortMappingCard] = []
        self.qualifier_cards: list[QuickSortMappingCard] = []
        self._loading_ui = False
        self._configuration_ready = False
        self._launch_ready = False
        self._eligible_count_key: tuple | None = None
        self._eligible_count_value: int | None = None
        self._all_loaded_count_value: int | None = None
        self._pending_count_key: tuple | None = None
        self._observed_context_key: tuple[int, int, int] | None = None
        self._context_signal_connections: list[tuple[object, object]] = []
        self._ui_zoom = max(
            60,
            min(160, int(settings.value("quick_sort_ui_zoom", 100, type=int) or 100)),
        )
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self._save_profiles)
        self._count_refresh_timer = QTimer(self)
        self._count_refresh_timer.setSingleShot(True)
        self._count_refresh_timer.setInterval(140)
        self._count_refresh_timer.timeout.connect(self._refresh_eligible_count)
        self._build_ui()
        self._apply_style()
        self._load_profiles()
        self._install_ui_zoom_filters()

    def _build_ui(self):
        root_widget = _CompressibleQuickSortRoot()
        root_widget.setObjectName("quickSortRoot")
        root_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(9)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.profile_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.add_profile_button = QPushButton("+")
        self.add_profile_button.setToolTip("Create a new profile")
        self.copy_profile_button = QPushButton("Copy")
        self.copy_profile_button.setToolTip("Duplicate this profile")
        self.delete_profile_button = QPushButton("×")
        self.delete_profile_button.setToolTip("Delete this profile")
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.add_profile_button)
        profile_row.addWidget(self.copy_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        root.addLayout(profile_row)

        self.scroll = _CompressibleQuickSortScroll()
        self.scroll.setObjectName("quickSortScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        content = QWidget()
        content.setObjectName("quickSortContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(9)

        source_row = QHBoxLayout()
        source_row.setSpacing(6)
        source_label = QLabel("Sort")
        source_label.setToolTip(
            "Choose which images from the active browser become this session's queue."
        )
        self.source_combo = QComboBox()
        self.source_combo.setToolTip(
            "Current folder uses the active browser folder. Other choices use the "
            "current selection or filter; this does not add another watched folder."
        )
        self.source_combo.setMinimumWidth(0)
        self.source_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.source_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source_combo.setMinimumContentsLength(4)
        for label, value in self.SOURCE_OPTIONS:
            self.source_combo.addItem(label, value)
        self.include_subfolders_check = QCheckBox("Include subfolders")
        self.include_videos_check = QCheckBox("Include videos")
        for checkbox in (
            self.include_subfolders_check,
            self.include_videos_check,
        ):
            checkbox.setMinimumWidth(0)
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        self.include_subfolders_check.setText("Subfolders")
        self.include_videos_check.setText("Videos")
        source_row.addWidget(source_label)
        source_row.addWidget(self.source_combo, 1)
        source_row.addWidget(self.include_subfolders_check)
        source_row.addWidget(self.include_videos_check)
        content_layout.addLayout(source_row)

        destination_header = QHBoxLayout()
        destination_title = QLabel("DESTINATIONS")
        destination_title.setObjectName("quickSortSectionTitle")
        self.destination_hint = QLabel("A-Z / 0-9 work automatically")
        self.destination_hint.setObjectName("quickSortMutedLabel")
        self.destination_hint.setMinimumWidth(0)
        self.destination_hint.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        destination_header.addWidget(destination_title)
        destination_header.addStretch(1)
        destination_header.addWidget(self.destination_hint)
        content_layout.addLayout(destination_header)
        self.standard_keys_check = QCheckBox(
            "Use automatic A-Z / 0-9 folders"
        )
        self.standard_keys_check.setMinimumWidth(0)
        self.standard_keys_check.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.standard_keys_check.setToolTip(
            "With no setup, pressing R sorts into folder R. Add a row below only "
            "when a key should use a descriptive name or a different folder."
        )
        content_layout.addWidget(self.standard_keys_check)
        destination_columns = QHBoxLayout()
        destination_columns.setContentsMargins(29, 0, 48, 0)
        destination_columns.setSpacing(5)
        key_column = QLabel("KEY")
        key_column.setFixedWidth(52)
        destination_column = QLabel("DESTINATION")
        for label in (key_column, destination_column):
            label.setObjectName("quickSortColumnLabel")
        destination_columns.addWidget(key_column)
        destination_columns.addWidget(destination_column, 1)
        content_layout.addLayout(destination_columns)
        self.destination_host = QWidget()
        self.destination_layout = QVBoxLayout(self.destination_host)
        self.destination_layout.setContentsMargins(0, 0, 0, 0)
        self.destination_layout.setSpacing(8)
        content_layout.addWidget(self.destination_host)
        self.add_destination_button = QPushButton("＋  Add destination override")
        self.add_destination_button.setObjectName("quickSortAddButton")
        destination_add_row = QHBoxLayout()
        destination_add_row.addStretch(1)
        destination_add_row.addWidget(self.add_destination_button)
        content_layout.addLayout(destination_add_row)

        qualifier_card = QWidget()
        qualifier_layout = QVBoxLayout(qualifier_card)
        qualifier_layout.setContentsMargins(0, 3, 0, 3)
        qualifier_layout.setSpacing(8)
        qualifier_top = QHBoxLayout()
        self.qualifier_enabled_check = QCheckBox("Use qualifiers (optional second key)")
        self.qualifier_enabled_check.setObjectName("quickSortQualifierToggle")
        self.qualifier_enabled_check.setMinimumWidth(0)
        self.qualifier_enabled_check.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.qualifier_enabled_check.setToolTip(
            "Turn on a first classification step, such as 1 = High quality, "
            "before pressing the destination key."
        )
        qualifier_top.addWidget(self.qualifier_enabled_check, 1)
        qualifier_layout.addLayout(qualifier_top)
        self.qualifier_options = QWidget()
        qualifier_options_layout = QVBoxLayout(self.qualifier_options)
        qualifier_options_layout.setContentsMargins(0, 2, 0, 0)
        qualifier_options_layout.setSpacing(8)
        qualifier_form = QFormLayout()
        qualifier_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.qualifier_name_edit = QLineEdit()
        self.qualifier_name_edit.setPlaceholderText("Quality")
        self.hierarchy_combo = QComboBox()
        self.hierarchy_combo.addItem("Destination / Qualifier", "destination_first")
        self.hierarchy_combo.addItem("Qualifier / Destination", "qualifier_first")
        self.missing_qualifier_combo = QComboBox()
        self.missing_qualifier_combo.addItem("Require a qualifier", "require")
        self.missing_qualifier_combo.addItem("Use Unclassified", "unclassified")
        self.unclassified_label = QLabel("Unclassified folder")
        self.unclassified_folder_edit = QLineEdit("Unclassified")
        self.unclassified_folder_edit.setPlaceholderText("Unclassified")
        for field in (
            self.qualifier_name_edit,
            self.hierarchy_combo,
            self.missing_qualifier_combo,
            self.unclassified_folder_edit,
        ):
            field.setMinimumWidth(0)
            field.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        for combo in (self.hierarchy_combo, self.missing_qualifier_combo):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(4)
        qualifier_form.addRow("Group name", self.qualifier_name_edit)
        qualifier_form.addRow("Folder order", self.hierarchy_combo)
        qualifier_form.addRow("If none chosen", self.missing_qualifier_combo)
        qualifier_form.addRow(
            self.unclassified_label,
            self.unclassified_folder_edit,
        )
        qualifier_options_layout.addLayout(qualifier_form)
        self.qualifier_host = QWidget()
        self.qualifier_cards_layout = QVBoxLayout(self.qualifier_host)
        self.qualifier_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.qualifier_cards_layout.setSpacing(8)
        qualifier_options_layout.addWidget(self.qualifier_host)
        self.add_qualifier_button = QPushButton("＋  Add qualifier")
        self.add_qualifier_button.setObjectName("quickSortAddButton")
        qualifier_add_row = QHBoxLayout()
        qualifier_add_row.addStretch(1)
        qualifier_add_row.addWidget(self.add_qualifier_button)
        qualifier_options_layout.addLayout(qualifier_add_row)
        qualifier_layout.addWidget(self.qualifier_options)
        content_layout.addWidget(qualifier_card)

        destination_layout = QVBoxLayout()
        destination_layout.setSpacing(5)
        base_row = QHBoxLayout()
        base_label = QLabel("Move to")
        base_label.setToolTip(
            "Parent folder for the key folders. Empty means the active browser folder."
        )
        self.base_destination_edit = QLineEdit()
        self.base_destination_edit.setPlaceholderText("Active folder")
        self.base_destination_edit.setToolTip(
            "Leave empty to create destination folders beside the images being sorted."
        )
        self.browse_destination_button = QPushButton("Browse…")
        base_row.addWidget(base_label)
        base_row.addWidget(self.base_destination_edit, 1)
        base_row.addWidget(self.browse_destination_button)
        destination_layout.addLayout(base_row)
        content_layout.addLayout(destination_layout)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("quickSortAdvancedToggle")
        self.advanced_toggle.setText("Advanced file behavior")
        self.advanced_toggle.setToolTip(
            "Choose move or copy behavior, filename-conflict handling, sidecars, "
            "and fullscreen startup. These settings do not change key mappings."
        )
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setMinimumWidth(0)
        self.advanced_toggle.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        content_layout.addWidget(self.advanced_toggle)
        self.advanced_frame = QFrame()
        self.advanced_frame.setObjectName("quickSortSection")
        advanced_form = QFormLayout(self.advanced_frame)
        advanced_form.setContentsMargins(10, 10, 10, 10)
        advanced_form.setSpacing(7)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        advanced_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.operation_combo = _CompressibleQuickSortCombo()
        for label, value in self.OPERATION_OPTIONS:
            self.operation_combo.addItem(label, value)
        self.collision_combo = _CompressibleQuickSortCombo()
        for label, value in self.COLLISION_OPTIONS:
            self.collision_combo.addItem(label, value)
        self.sidecars_check = QCheckBox("Move/copy captions and metadata sidecars")
        self.fullscreen_check = QCheckBox("Start in fullscreen")
        for field in (self.operation_combo, self.collision_combo):
            field.setMinimumWidth(0)
            field.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            field.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            field.setMinimumContentsLength(4)
        for checkbox in (self.sidecars_check, self.fullscreen_check):
            checkbox.setMinimumWidth(0)
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        self.operation_combo.setToolTip(
            "Move removes the source after a successful sort. Copy leaves the "
            "source file in place and creates a destination copy."
        )
        self.collision_combo.setToolTip(
            "Controls what happens when the destination already contains the same filename."
        )
        advanced_form.addRow("After a key press", self.operation_combo)
        advanced_form.addRow("If the filename exists", self.collision_combo)
        advanced_form.addRow(self.sidecars_check)
        advanced_form.addRow(self.fullscreen_check)
        self.advanced_frame.hide()
        content_layout.addWidget(self.advanced_frame)
        content_layout.addStretch(1)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        self.run_panel = QFrame()
        self.run_panel.setObjectName("quickSortRunPanel")
        run_layout = QVBoxLayout(self.run_panel)
        run_layout.setContentsMargins(10, 9, 10, 10)
        run_layout.setSpacing(7)
        status_row = QHBoxLayout()
        self.validation_chip = QLabel("READY")
        self.validation_chip.setObjectName("quickSortValidationChip")
        self.summary_label = QLabel("Configure at least one destination")
        self.summary_label.setObjectName("quickSortRunSummary")
        self.summary_label.setWordWrap(True)
        self.reset_progress_button = QPushButton("Start fresh")
        self.reset_progress_button.setToolTip(
            "Forget remembered sorted/skipped decisions for this profile and folder."
        )
        status_row.addWidget(self.validation_chip)
        status_row.addWidget(self.summary_label, 1)
        status_row.addWidget(self.reset_progress_button)
        run_layout.addLayout(status_row)
        self.scope_notice = QFrame()
        self.scope_notice.setObjectName("quickSortScopeNotice")
        scope_notice_layout = QHBoxLayout(self.scope_notice)
        scope_notice_layout.setContentsMargins(8, 6, 7, 6)
        scope_notice_layout.setSpacing(7)
        self.scope_notice_label = QLabel()
        self.scope_notice_label.setObjectName("quickSortScopeNoticeText")
        self.scope_notice_label.setWordWrap(True)
        self.scope_notice_label.setMinimumWidth(0)
        self.include_all_loaded_button = QPushButton("Include all")
        self.include_all_loaded_button.setObjectName("quickSortScopeAction")
        self.include_all_loaded_button.setToolTip(
            "Switch the queue from this folder only to all media loaded by the browser."
        )
        scope_notice_layout.addWidget(self.scope_notice_label, 1)
        scope_notice_layout.addWidget(self.include_all_loaded_button)
        self.scope_notice.hide()
        run_layout.addWidget(self.scope_notice)
        self.start_button = QPushButton("Start Quick Sort")
        self.start_button.setObjectName("quickSortRunButton")
        run_layout.addWidget(self.start_button)
        root.addWidget(self.run_panel)
        self.setWidget(root_widget)

        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.profile_combo.lineEdit().editingFinished.connect(
            self._rename_current_profile
        )
        self.add_profile_button.clicked.connect(self._add_profile)
        self.copy_profile_button.clicked.connect(self._copy_profile)
        self.delete_profile_button.clicked.connect(self._delete_profile)
        self.add_destination_button.clicked.connect(self._add_destination)
        self.add_qualifier_button.clicked.connect(self._add_qualifier)
        self.standard_keys_check.toggled.connect(self._schedule_save)
        self.qualifier_enabled_check.toggled.connect(self._qualifier_toggled)
        self.source_combo.currentIndexChanged.connect(self._source_scope_changed)
        self.include_subfolders_check.toggled.connect(
            self._invalidate_eligible_count
        )
        self.include_videos_check.toggled.connect(self._invalidate_eligible_count)
        self.missing_qualifier_combo.currentIndexChanged.connect(
            self._update_unclassified_visibility
        )
        self.browse_destination_button.clicked.connect(self._browse_destination)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.start_button.clicked.connect(self._start)
        self.reset_progress_button.clicked.connect(self._clear_saved_progress)
        self.include_all_loaded_button.clicked.connect(self._include_all_loaded)
        for widget_signal in (
            self.source_combo.currentIndexChanged,
            self.include_subfolders_check.toggled,
            self.include_videos_check.toggled,
            self.qualifier_name_edit.textChanged,
            self.hierarchy_combo.currentIndexChanged,
            self.missing_qualifier_combo.currentIndexChanged,
            self.unclassified_folder_edit.textChanged,
            self.base_destination_edit.textChanged,
            self.operation_combo.currentIndexChanged,
            self.collision_combo.currentIndexChanged,
            self.sidecars_check.toggled,
            self.fullscreen_check.toggled,
        ):
            widget_signal.connect(self._schedule_save)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str):
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _clear_card_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_cards(
        self,
        mappings: list[QuickSortMapping],
        *,
        kind: str,
    ):
        if kind == "destination":
            layout = self.destination_layout
            self.destination_cards = []
            target = self.destination_cards
        else:
            layout = self.qualifier_cards_layout
            self.qualifier_cards = []
            target = self.qualifier_cards
        self._clear_card_layout(layout)
        for mapping in mappings:
            card = QuickSortMappingCard(mapping, kind=kind)
            self._install_zoom_filter_tree(card)
            card.changed.connect(self._schedule_save)
            card.remove_requested.connect(
                lambda mapping_id, mapping_kind=kind: self._remove_mapping(
                    mapping_kind,
                    mapping_id,
                )
            )
            layout.addWidget(card)
            target.append(card)

    def _current_profile(self) -> QuickSortProfile | None:
        return next(
            (profile for profile in self.profiles if profile.id == self.current_profile_id),
            None,
        )

    def _profile_from_ui(self) -> QuickSortProfile:
        current = self._current_profile()
        if current is None:
            raise QuickSortValidationError("No Quick Sort profile is selected.")
        return QuickSortProfile(
            id=current.id,
            schema_version=current.schema_version,
            # ``currentIndexChanged`` fires after the combo has already switched
            # its visible text.  The fields still belong to ``current`` at that
            # point, so using currentText() here would silently rename the old
            # profile to the newly selected profile's name.
            name=current.name,
            destinations=[card.mapping() for card in self.destination_cards],
            standard_key_destinations=self.standard_keys_check.isChecked(),
            qualifiers=[card.mapping() for card in self.qualifier_cards],
            qualifier_enabled=self.qualifier_enabled_check.isChecked(),
            qualifier_name=self.qualifier_name_edit.text().strip() or "Quality",
            hierarchy_order=str(self.hierarchy_combo.currentData() or "destination_first"),
            missing_qualifier=str(self.missing_qualifier_combo.currentData() or "require"),
            unclassified_folder=(
                self.unclassified_folder_edit.text().strip() or "Unclassified"
            ),
            base_destination=self.base_destination_edit.text().strip(),
            source_scope=str(self.source_combo.currentData() or "current_folder"),
            include_subfolders=self.include_subfolders_check.isChecked(),
            include_videos=self.include_videos_check.isChecked(),
            operation_mode=str(self.operation_combo.currentData() or "move"),
            collision_policy=str(self.collision_combo.currentData() or "append"),
            include_sidecars=self.sidecars_check.isChecked(),
            start_fullscreen=self.fullscreen_check.isChecked(),
        )

    def _load_profile_into_ui(self, profile: QuickSortProfile):
        self._loading_ui = True
        try:
            self.current_profile_id = profile.id
            self.profile_combo.setEditText(profile.name)
            self._set_combo_data(self.source_combo, profile.source_scope)
            self.include_subfolders_check.setChecked(profile.include_subfolders)
            self.include_videos_check.setChecked(profile.include_videos)
            self.standard_keys_check.setChecked(profile.standard_key_destinations)
            self.qualifier_enabled_check.setChecked(profile.qualifier_enabled)
            self.qualifier_name_edit.setText(profile.qualifier_name)
            self._set_combo_data(self.hierarchy_combo, profile.hierarchy_order)
            self._set_combo_data(self.missing_qualifier_combo, profile.missing_qualifier)
            self.unclassified_folder_edit.setText(profile.unclassified_folder)
            self.base_destination_edit.setText(profile.base_destination)
            self._set_combo_data(self.operation_combo, profile.operation_mode)
            self._set_combo_data(self.collision_combo, profile.collision_policy)
            self.sidecars_check.setChecked(profile.include_sidecars)
            self.fullscreen_check.setChecked(profile.start_fullscreen)
            self._populate_cards(profile.destinations, kind="destination")
            self._populate_cards(profile.qualifiers, kind="qualifier")
            self.qualifier_options.setVisible(profile.qualifier_enabled)
            self._source_scope_changed()
            self._update_unclassified_visibility()
        finally:
            self._loading_ui = False
        self._refresh_summary()

    def _load_profiles(self):
        try:
            self.profiles = self.store.load()
        except QuickSortValidationError as exc:
            QMessageBox.warning(self, "Quick Sort profiles", str(exc))
            self.profiles = []
        if not self.profiles:
            self.profiles = [default_quick_sort_profile()]
            try:
                self.store.save(self.profiles)
            except (OSError, QuickSortValidationError):
                pass
        selected_id = str(settings.value("quick_sort_profile_id", "", type=str) or "")
        selected = next(
            (profile for profile in self.profiles if profile.id == selected_id),
            self.profiles[0],
        )
        self._rebuild_profile_combo(selected.id)
        self._load_profile_into_ui(selected)

    def _rebuild_profile_combo(self, selected_id: str | None = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.profiles:
            self.profile_combo.addItem(profile.name, profile.id)
        index = self.profile_combo.findData(selected_id)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def _commit_current_ui(self, *, validate: bool) -> QuickSortProfile | None:
        if self._loading_ui or self._current_profile() is None:
            return None
        try:
            profile = self._profile_from_ui()
            profile.validate()
        except QuickSortValidationError:
            if validate:
                raise
            return None
        for index, existing in enumerate(self.profiles):
            if existing.id == profile.id:
                self.profiles[index] = profile
                break
        self.current_profile_id = profile.id
        return profile

    def _persist_profiles(self, profile: QuickSortProfile) -> bool:
        """Persist a committed profile set without changing the visible draft."""
        try:
            self.store.save(self.profiles)
        except (OSError, QuickSortValidationError) as exc:
            self._set_validation_state("error", "SAVE FAILED")
            self.summary_label.setText(str(exc))
            return False
        settings.setValue("quick_sort_profile_id", profile.id)
        return True

    def _save_profiles(self) -> bool:
        if self._loading_ui:
            return False
        profile = self._commit_current_ui(validate=False)
        if profile is None:
            self._refresh_summary()
            return False
        if not self._persist_profiles(profile):
            return False
        self._refresh_summary()
        return True

    def _schedule_save(self, *_args):
        if self._loading_ui:
            return
        self._refresh_summary()
        self._save_timer.start()

    def _restore_current_profile_selection(self):
        """Put the combo back on the profile whose draft is still visible."""
        index = self.profile_combo.findData(self.current_profile_id)
        if index < 0:
            return
        was_blocked = self.profile_combo.blockSignals(True)
        try:
            self.profile_combo.setCurrentIndex(index)
            current = self._current_profile()
            if current is not None:
                self.profile_combo.setEditText(current.name)
        finally:
            self.profile_combo.blockSignals(was_blocked)

    def _prepare_profile_transition(self) -> QuickSortProfile | None:
        """Commit and persist the current draft before another profile is shown."""
        self._save_timer.stop()
        try:
            profile = self._commit_current_ui(validate=True)
        except QuickSortValidationError:
            self._refresh_summary()
            return None
        if profile is None or not self._persist_profiles(profile):
            return None
        return profile

    def _profile_changed(self, index: int):
        if self._loading_ui or index < 0:
            return
        profile_id = str(self.profile_combo.itemData(index) or "")
        if profile_id == self.current_profile_id:
            return
        if self._prepare_profile_transition() is None:
            self._restore_current_profile_selection()
            return
        profile = next(
            (item for item in self.profiles if item.id == profile_id),
            None,
        )
        if profile is None:
            self._restore_current_profile_selection()
            return
        self._load_profile_into_ui(profile)
        settings.setValue("quick_sort_profile_id", profile.id)

    def _rename_current_profile(self):
        if self._loading_ui:
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
        name, accepted = QInputDialog.getText(
            self,
            "New Quick Sort profile",
            "Profile name:",
            text="New Quick Sort",
        )
        if not accepted or not name.strip():
            return
        if self._prepare_profile_transition() is None:
            return
        profile = default_quick_sort_profile(name.strip())
        self.profiles.append(profile)
        self._rebuild_profile_combo(profile.id)
        self._load_profile_into_ui(profile)
        self._save_timer.start(0)

    def _copy_profile(self):
        current = self._prepare_profile_transition()
        if current is None:
            return
        duplicate = deepcopy(current)
        duplicate.id = new_quick_sort_id("profile")
        duplicate.name = f"{current.name} Copy"
        for mapping in duplicate.destinations + duplicate.qualifiers:
            mapping.id = new_quick_sort_id("route")
        self.profiles.append(duplicate)
        self._rebuild_profile_combo(duplicate.id)
        self._load_profile_into_ui(duplicate)
        self._save_timer.start(0)

    def _delete_profile(self):
        current = self._current_profile()
        if current is None:
            return
        if len(self.profiles) <= 1:
            QMessageBox.information(
                self,
                "Quick Sort profiles",
                "At least one Quick Sort profile must remain.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Delete Quick Sort profile",
            f"Delete {current.name!r}?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.profiles = [profile for profile in self.profiles if profile.id != current.id]
        selected = self.profiles[0]
        self._rebuild_profile_combo(selected.id)
        self._load_profile_into_ui(selected)
        self._save_timer.start(0)

    def _next_default_key(self, cards: list[QuickSortMappingCard]) -> str:
        used = {card.key_button.key.casefold() for card in cards}
        for candidate in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            if candidate.casefold() not in used:
                return candidate
        return "F1"

    def _next_mapping_color(self, cards: list[QuickSortMappingCard]) -> str:
        """Return a contrasting color not already used by this mapping group."""
        used = {str(card.color).casefold() for card in cards}
        for color in _MAPPING_COLOR_PALETTE:
            if color.casefold() not in used:
                return color

        # Keep producing distinct colors when a profile outgrows the palette.
        offset = len(cards) - len(_MAPPING_COLOR_PALETTE)
        for attempt in range(360):
            hue = (offset * 137 + attempt * 29) % 360
            color = QColor.fromHsv(hue, 170, 240).name()
            if color.casefold() not in used:
                return color
        return "#62E7D8"

    def _add_destination(self):
        number = len(self.destination_cards) + 1
        mapping = QuickSortMapping(
            name=f"Destination {number}",
            key=self._next_default_key(self.destination_cards),
            folder=f"Destination {number}",
            color=self._next_mapping_color(self.destination_cards),
        )
        card = QuickSortMappingCard(mapping, kind="destination")
        self._install_zoom_filter_tree(card)
        card.changed.connect(self._schedule_save)
        card.remove_requested.connect(
            lambda mapping_id: self._remove_mapping("destination", mapping_id)
        )
        self.destination_layout.addWidget(card)
        self.destination_cards.append(card)
        self._schedule_save()

    def _add_qualifier(self):
        number = len(self.qualifier_cards) + 1
        mapping = QuickSortMapping(
            name=f"Qualifier {number}",
            key=str(number) if number <= 9 else self._next_default_key(self.qualifier_cards),
            folder=f"Qualifier {number}",
            color=self._next_mapping_color(self.qualifier_cards),
        )
        card = QuickSortMappingCard(mapping, kind="qualifier")
        self._install_zoom_filter_tree(card)
        card.changed.connect(self._schedule_save)
        card.remove_requested.connect(
            lambda mapping_id: self._remove_mapping("qualifier", mapping_id)
        )
        self.qualifier_cards_layout.addWidget(card)
        self.qualifier_cards.append(card)
        self._schedule_save()

    def _remove_mapping(self, kind: str, mapping_id: str):
        cards = self.destination_cards if kind == "destination" else self.qualifier_cards
        card = next((item for item in cards if item.mapping_id == mapping_id), None)
        if card is None:
            return
        cards.remove(card)
        card.setParent(None)
        card.deleteLater()
        self._schedule_save()

    def _qualifier_toggled(self, checked: bool):
        self.qualifier_options.setVisible(bool(checked))
        self._schedule_save()

    def _source_scope_changed(self, *_args):
        current_folder = self.source_combo.currentData() == "current_folder"
        self.include_subfolders_check.setEnabled(current_folder)
        self.include_subfolders_check.setToolTip(
            "Include existing nested folders in the immutable session queue."
            if current_folder
            else "This scope already determines which nested media is included."
        )
        if not self._loading_ui:
            self._invalidate_eligible_count()

    def _include_all_loaded(self):
        index = self.source_combo.findData("all_loaded")
        if index >= 0:
            self.source_combo.setCurrentIndex(index)

    def _update_unclassified_visibility(self, *_args):
        visible = self.missing_qualifier_combo.currentData() == "unclassified"
        self.unclassified_label.setVisible(visible)
        self.unclassified_folder_edit.setVisible(visible)

    def _browse_destination(self):
        initial = self.base_destination_edit.text().strip()
        if not initial:
            context = self._active_browser_context()
            directory = getattr(context["model"], "_directory_path", None)
            initial = str(directory or "")
        selected = QFileDialog.getExistingDirectory(
            self,
            "Quick Sort destination base",
            initial,
        )
        if selected:
            self.base_destination_edit.setText(str(Path(selected).resolve()))

    def _toggle_advanced(self, checked: bool):
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self.advanced_frame.setVisible(checked)

    def _active_browser_context(self) -> dict:
        if self.controller is not None:
            return self.controller.resolve_browser_context()
        return {
            "name": "primary",
            "model": self.main_window.image_list_model,
            "proxy": self.main_window.proxy_image_list_model,
            "image_list": self.main_window.image_list,
            "owner": self.main_window,
        }

    @property
    def is_ready(self) -> bool:
        """Whether the current panel state can launch a Quick Sort session."""
        return self._launch_ready

    def _set_configuration_ready(self, ready: bool):
        self._configuration_ready = bool(ready)
        self._sync_launch_readiness()

    def _sync_launch_readiness(self):
        controller_active = bool(
            self.controller is not None
            and getattr(self.controller, "active", False)
        )
        ready = bool(
            self._configuration_ready
            and self.controller is not None
            and not controller_active
        )
        self.start_button.setEnabled(ready)
        if ready == self._launch_ready:
            return
        self._launch_ready = ready
        self.readiness_changed.emit(ready)

    @staticmethod
    def _row_count(model) -> int | None:
        try:
            return int(model.rowCount())
        except Exception:
            return None

    def _selected_count(self, image_list) -> int | None:
        try:
            if hasattr(image_list, "get_selected_image_count"):
                return int(image_list.get_selected_image_count())
            list_view = getattr(image_list, "list_view", None)
            if list_view is not None and hasattr(
                list_view,
                "get_selected_image_count",
            ):
                return int(list_view.get_selected_image_count())
        except Exception:
            pass
        return None

    def _eligible_count_cache_key(
        self,
        profile: QuickSortProfile,
        context: dict,
    ) -> tuple:
        model = context["model"]
        proxy = context["proxy"]
        image_list = context["image_list"]
        if profile.source_scope == "selected":
            scope_state = ("selected", self._selected_count(image_list))
        elif profile.source_scope == "filtered":
            scope_state = (
                "filtered",
                str(getattr(model, "_filter_sql", "") or ""),
                repr(tuple(getattr(model, "_filter_bindings", ()) or ())),
                self._row_count(proxy),
            )
        else:
            scope_state = (
                "loaded",
                str(getattr(model, "_scope_sql", "") or ""),
                repr(tuple(getattr(model, "_scope_bindings", ()) or ())),
                getattr(model, "_total_count", None),
                self._row_count(model),
            )
        return (
            str(context.get("name") or "primary"),
            id(model),
            id(proxy),
            id(image_list),
            repr(getattr(model, "_directory_path", None)),
            bool(getattr(model, "_paginated_mode", False)),
            profile.source_scope,
            bool(profile.include_subfolders),
            bool(profile.include_videos),
            scope_state,
        )

    def _disconnect_context_signals(self):
        for signal, slot in self._context_signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._context_signal_connections.clear()

    def _observe_browser_context(self, context: dict):
        model = context["model"]
        proxy = context["proxy"]
        image_list = context["image_list"]
        context_key = (id(model), id(proxy), id(image_list))
        if context_key == self._observed_context_key:
            return
        self._disconnect_context_signals()
        self._observed_context_key = context_key

        objects_and_signals = (
            (model, "modelReset"),
            (model, "rowsInserted"),
            (model, "rowsRemoved"),
            (proxy, "filter_changed"),
            (proxy, "modelReset"),
        )
        for obj, signal_name in objects_and_signals:
            signal = getattr(obj, signal_name, None)
            if signal is None or not hasattr(signal, "connect"):
                continue
            slot = self._browser_context_changed
            try:
                signal.connect(slot)
            except (RuntimeError, TypeError):
                continue
            self._context_signal_connections.append((signal, slot))

        list_view = getattr(image_list, "list_view", None)
        try:
            selection_model = (
                list_view.selectionModel() if list_view is not None else None
            )
        except RuntimeError:
            selection_model = None
        selection_changed = getattr(selection_model, "selectionChanged", None)
        if selection_changed is not None and hasattr(selection_changed, "connect"):
            slot = self._browser_context_changed
            try:
                selection_changed.connect(slot)
            except (RuntimeError, TypeError):
                pass
            else:
                self._context_signal_connections.append((selection_changed, slot))

    def _clear_eligible_count_cache(self):
        self._eligible_count_key = None
        self._eligible_count_value = None
        self._all_loaded_count_value = None
        self._pending_count_key = None

    def _browser_context_changed(self, *_args):
        self._invalidate_eligible_count()

    def _invalidate_eligible_count(self, *_args):
        self._clear_eligible_count_cache()
        if self._loading_ui:
            return
        self._set_configuration_ready(False)
        if self.controller is None or bool(getattr(self.controller, "active", False)):
            self._count_refresh_timer.stop()
            return
        self._set_validation_state("warning", "COUNTING")
        self._count_refresh_timer.start()

    def _eligible_count(
        self,
        profile: QuickSortProfile,
        context: dict,
    ) -> int | None:
        key = self._eligible_count_cache_key(profile, context)
        if key == self._eligible_count_key and self._eligible_count_value is not None:
            return self._eligible_count_value
        if self.controller is None or bool(getattr(self.controller, "active", False)):
            return None
        if key != self._pending_count_key:
            self._pending_count_key = key
            self._count_refresh_timer.start()
        elif not self._count_refresh_timer.isActive():
            self._count_refresh_timer.start()
        return None

    def _refresh_eligible_count(self):
        if self._loading_ui or self.controller is None:
            return
        if bool(getattr(self.controller, "active", False)):
            return
        try:
            profile = self._profile_from_ui()
            profile.validate()
            context = self._active_browser_context()
            self._observe_browser_context(context)
        except (QuickSortValidationError, KeyError, RuntimeError):
            self._pending_count_key = None
            self._refresh_summary()
            return
        if getattr(context["model"], "_directory_path", None) is None:
            self._pending_count_key = None
            self._refresh_summary()
            return
        key = self._eligible_count_cache_key(profile, context)
        try:
            count = max(0, int(self.controller.estimate_queue_count(profile, context)))
        except Exception:
            count = 0
        all_loaded_count = None
        if profile.source_scope == "current_folder" and not profile.include_subfolders:
            all_loaded_profile = deepcopy(profile)
            all_loaded_profile.source_scope = "all_loaded"
            try:
                all_loaded_count = max(
                    count,
                    int(self.controller.estimate_queue_count(all_loaded_profile, context)),
                )
            except Exception:
                all_loaded_count = count
        self._eligible_count_key = key
        self._eligible_count_value = count
        self._all_loaded_count_value = all_loaded_count
        self._pending_count_key = None
        self._refresh_summary()

    def _set_validation_state(self, state: str, text: str):
        self.validation_chip.setText(text)
        self.validation_chip.setProperty("state", state)
        self.validation_chip.style().unpolish(self.validation_chip)
        self.validation_chip.style().polish(self.validation_chip)

    def _refresh_summary(self):
        try:
            profile = self._profile_from_ui()
            profile.validate()
        except QuickSortValidationError as exc:
            self._set_validation_state("error", "CHECK")
            self.summary_label.setText(str(exc))
            self._set_configuration_ready(False)
            return
        try:
            context = self._active_browser_context()
            self._observe_browser_context(context)
        except (KeyError, RuntimeError):
            self._set_validation_state("warning", "NO CONTEXT")
            self.summary_label.setText("Quick Sort cannot access the active browser.")
            self._set_configuration_ready(False)
            return
        qualifier_text = (
            f" · {len(profile.enabled_qualifiers())} {profile.qualifier_name.lower()} choices"
            if profile.qualifier_enabled
            else ""
        )
        if getattr(context["model"], "_directory_path", None) is None:
            self._set_validation_state("warning", "NO FOLDER")
            self.summary_label.setText("Load a folder to prepare a Quick Sort queue.")
            self._set_configuration_ready(False)
            return
        if self.controller is None:
            self._set_validation_state("warning", "WAITING")
            self.summary_label.setText("Quick Sort is still connecting to the browser.")
            self._set_configuration_ready(False)
            return
        count = self._eligible_count(profile, context)
        count_text = "Counting…" if count is None else f"{count:,} media"
        destination_text = (
            "A-Z / 0-9 automatic"
            if profile.standard_key_destinations
            else f"{len(profile.enabled_destinations())} destinations"
        )
        override_count = len(profile.enabled_destinations())
        if profile.standard_key_destinations and override_count:
            destination_text += f" · {override_count} overrides"
        self.summary_label.setText(
            f"{count_text} · {destination_text}"
            f"{qualifier_text} · {profile.operation_mode.title()} mode"
        )
        self.scope_notice.hide()
        if count is None:
            self.start_button.setText("Start Quick Sort")
        else:
            scope_labels = {
                "current_folder": "from this folder",
                "selected": "selected",
                "filtered": "matching the current filter",
                "all_loaded": "across all loaded folders",
            }
            self.summary_label.setText(
                f"{count:,} media {scope_labels.get(profile.source_scope, '')} · "
                f"{destination_text}{qualifier_text} · "
                f"{profile.operation_mode.title()} mode"
            )
            self.start_button.setText(f"Start with {count:,} media")
            if (
                profile.source_scope == "current_folder"
                and not profile.include_subfolders
                and self._all_loaded_count_value is not None
                and self._all_loaded_count_value > count
            ):
                additional = self._all_loaded_count_value - count
                self.scope_notice_label.setText(
                    f"{additional:,} more media available in subfolders."
                )
                self.include_all_loaded_button.setText(
                    f"Include all {self._all_loaded_count_value:,}"
                )
                self.scope_notice.show()
        if count is None:
            self._set_validation_state("warning", "COUNTING")
            self._set_configuration_ready(False)
        elif count <= 0:
            self._set_validation_state("warning", "EMPTY")
            self._set_configuration_ready(False)
        else:
            self._set_validation_state("ready", "READY")
            self._set_configuration_ready(True)

    def _start(self):
        if self.controller is None:
            return
        self._rename_current_profile()
        try:
            profile = self._profile_from_ui()
            profile.validate()
        except QuickSortValidationError as exc:
            QMessageBox.warning(self, "Quick Sort", str(exc))
            return
        self._commit_current_ui(validate=True)
        if not self._save_profiles() or not self.is_ready:
            return
        self.start_requested.emit(profile)

    def start_quick_sort(self):
        """Launch the configured profile from either the panel or main menu."""
        self._start()

    def _clear_saved_progress(self):
        if self.controller is None:
            return
        try:
            profile = self._profile_from_ui()
            profile.validate()
        except QuickSortValidationError as exc:
            QMessageBox.warning(self, "Quick Sort", str(exc))
            return
        if self.controller.clear_saved_session(profile):
            self.summary_label.setText(
                "Remembered Quick Sort progress cleared. The next run starts fresh."
            )

    def bind_controller(self, controller):
        self.controller = controller
        self.start_requested.connect(controller.start_session)
        controller.active_changed.connect(self._controller_active_changed)
        controller.session_finished.connect(self._session_finished)
        self._clear_eligible_count_cache()
        self._refresh_summary()

    def _controller_active_changed(self, active: bool):
        self.start_button.setText("Quick Sort Running" if active else "Start Quick Sort")
        if active:
            self._sync_launch_readiness()
        else:
            # ``session_finished`` follows this signal and owns the delayed
            # post-session recount.  Clearing readiness here avoids briefly
            # re-enabling launch with the pre-session count.
            self._set_configuration_ready(False)

    def _session_finished(self, summary: dict):
        self._count_refresh_timer.stop()
        self._clear_eligible_count_cache()
        self._set_configuration_ready(False)
        changed = int(summary.get("changed", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        remaining = int(summary.get("remaining", 0) or 0)
        remaining_text = f" · {remaining:,} left" if remaining else ""
        self.summary_label.setText(
            f"Last session: {changed:,} changed · {skipped:,} skipped"
            f"{remaining_text}"
        )
        QTimer.singleShot(1800, self._refresh_summary)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_summary()

    def _install_zoom_filter_tree(self, widget: QWidget):
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def _install_ui_zoom_filters(self):
        root = self.widget()
        if root is not None:
            self._install_zoom_filter_tree(root)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._adjust_ui_zoom(
                event.angleDelta().y() or event.pixelDelta().y()
            )
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._adjust_ui_zoom(
                event.angleDelta().y() or event.pixelDelta().y()
            )
            event.accept()
            return
        super().wheelEvent(event)

    def _adjust_ui_zoom(self, wheel_delta: int):
        if not wheel_delta:
            return
        delta = 10 if wheel_delta > 0 else -10
        next_zoom = max(60, min(160, self._ui_zoom + delta))
        if next_zoom == self._ui_zoom:
            return
        self._ui_zoom = next_zoom
        settings.setValue("quick_sort_ui_zoom", next_zoom)
        self._apply_style()
        self._update_compact_visibility()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_visibility()

    def _update_compact_visibility(self):
        scale = max(0.01, self._ui_zoom / 100.0)
        effective_height = self.height() / scale
        effective_width = self.width() / scale
        compact_width = effective_width < 360
        self.copy_profile_button.setText("…" if compact_width else "Copy")
        self.reset_progress_button.setText("Fresh" if compact_width else "Start fresh")
        self.destination_hint.setVisible(effective_width >= 500)
        self.qualifier_enabled_check.setText(
            "Use qualifiers" if compact_width else "Use qualifiers (optional second key)"
        )
        self.advanced_toggle.setText(
            "File behavior" if compact_width else "Advanced file behavior"
        )
        self.add_destination_button.setText(
            "＋  Override" if compact_width else "＋  Add named override"
        )
        self.add_qualifier_button.setText(
            "＋  Qualifier" if compact_width else "＋  Add qualifier"
        )
        self.sidecars_check.setText(
            "Include sidecars"
            if compact_width
            else "Move/copy captions and metadata sidecars"
        )
        self.fullscreen_check.setText(
            "Start fullscreen" if compact_width else "Start in fullscreen"
        )
        self.include_subfolders_check.setText(
            "Subs" if compact_width else "Subfolders"
        )
        self.include_videos_check.setText("Video" if compact_width else "Videos")
        if self.controller is None or not self.controller.active:
            self.start_button.setText("Start" if compact_width else "Start Quick Sort")

    def _apply_style(self):
        scale = self._ui_zoom / 100.0
        font_size = max(9, round(11 * scale))
        self.setStyleSheet("")
        root_widget = self.widget()
        if root_widget is None:
            return
        root_widget.setStyleSheet(
            f"""
            QWidget {{ font-size: {font_size}px; }}
            QWidget#quickSortRoot, QWidget#qt_scrollarea_viewport,
            QScrollArea#quickSortScroll, QWidget#quickSortContent {{
                background: #303030;
            }}
            QScrollArea#quickSortScroll {{ border: 0; }}
            QFrame#quickSortSection {{ background: #383838; border: 1px solid #4A4A4A; border-radius: 6px; }}
            QLabel#quickSortSectionTitle {{ color: #E0E0E0; font-weight: 700; }}
            QLabel#quickSortMutedLabel {{ color: #9E9E9E; }}
            QLabel#quickSortColumnLabel {{ color: #8E8E8E; font-size: {max(8, round(9 * scale))}px; font-weight: 700; }}
            QFrame#quickSortMappingCard {{ background: #383838; border: 1px solid #4A4A4A; border-radius: 5px; }}
            QLineEdit, QComboBox {{
                color: #E8E8E8; background: #242424; border: 1px solid #4A4A4A;
                border-radius: 6px; padding: 4px 7px; min-height: {max(18, round(22 * scale))}px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color: #7AA2FF; }}
            QPushButton {{
                color: #E0E0E0; background: #3A3A3A; border: 1px solid #4A4A4A;
                border-radius: 6px; padding: 4px 8px;
            }}
            QPushButton:hover {{ background: #4A4A4A; border-color: #5A5A5A; }}
            QPushButton#quickSortKeyButton {{ color: #FFFFFF; font-weight: 800; background: #303030; }}
            QPushButton#quickSortKeyButton[capturing="true"] {{ color: #FFFFFF; background: #3B82F6; }}
            QPushButton#quickSortRemoveButton {{ color: #FF9B9B; font-weight: 900; padding: 0; }}
            QPushButton#quickSortAddButton {{
                color: #BDBDBD; background: #303030; border: 1px solid #454545;
                padding: 5px; font-weight: 700;
            }}
            QPushButton#quickSortAddButton:hover {{ border-color: #6A6A6A; background: #3A3A3A; }}
            QToolButton#quickSortAdvancedToggle {{
                color: #BDBDBD; background: transparent; border: 0; padding: 5px; font-weight: 700;
            }}
            QFrame#quickSortRunPanel {{ background: #383838; border: 1px solid #4A4A4A; border-radius: 6px; }}
            QLabel#quickSortRunSummary {{ color: #BDBDBD; }}
            QFrame#quickSortScopeNotice {{ background: #303842; border: 1px solid #506071; border-radius: 5px; }}
            QLabel#quickSortScopeNoticeText {{ color: #D8E4EF; }}
            QPushButton#quickSortScopeAction {{
                color: #DDEBFF; background: #3C526B; border: 1px solid #617A94;
                border-radius: 5px; padding: 4px 8px; font-weight: 700;
            }}
            QPushButton#quickSortScopeAction:hover {{ background: #48627E; }}
            QLabel#quickSortValidationChip {{ border-radius: 6px; padding: 3px 7px; font-weight: 900; }}
            QLabel#quickSortValidationChip[state="ready"] {{ color: #8ED9B0; background: #203A2D; }}
            QLabel#quickSortValidationChip[state="warning"] {{ color: #F3CF79; background: #40351F; }}
            QLabel#quickSortValidationChip[state="error"] {{ color: #FF9B9B; background: #482828; }}
            QPushButton#quickSortRunButton {{
                color: #FFFFFF; background: #3B82F6; border: 0; border-radius: 6px;
                padding: {max(7, round(9 * scale))}px 12px; font-weight: 900;
            }}
            QPushButton#quickSortRunButton:hover {{ background: #4F8EF7; }}
            QPushButton#quickSortRunButton:disabled {{ color: #777777; background: #353535; }}
            QCheckBox {{ color: #E0E0E0; spacing: 6px; }}
            QCheckBox#quickSortQualifierToggle {{ color: #E0E0E0; font-weight: 700; }}
            """
        )
