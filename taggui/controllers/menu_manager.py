"""Manager for main window menu bar."""

from pathlib import Path
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QKeySequence, QPalette
from PySide6.QtCore import QEvent, QSize, QTimer, QUrl, Qt, Signal

from utils.settings import settings, DEFAULT_SETTINGS
try:
    from version import APP_DISPLAY_NAME, __version__
except ImportError:
    from ..version import APP_DISPLAY_NAME, __version__


GITHUB_REPOSITORY_URL = 'https://github.com/diodiogod/taggui-video'
DOCUMENTATION_HUB_URL = f'{GITHUB_REPOSITORY_URL}/blob/main/docs/HUB.md'


class RecentFoldersListWidget(QListWidget):
    """Scrollable recent-folders list embedded inside the File menu."""

    open_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setAlternatingRowColors(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSpacing(0)
        self.setStyleSheet(
            "QListWidget { border: none; outline: none; background: transparent; }"
            "QListWidget::item { border: none; padding: 0px; margin: 0px; }"
        )
        self.currentItemChanged.connect(lambda *_: self._refresh_row_states())
        self.itemClicked.connect(self._open_item)
        self.itemEntered.connect(self._track_hover_item)

    def mouseMoveEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None:
            self.setCurrentItem(item)
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_item_widths()

    def leaveEvent(self, event):
        self.clearSelection()
        self.setCurrentRow(-1)
        self._refresh_row_states()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            item = self.currentItem()
            if item is not None:
                folder_path = item.data(Qt.ItemDataRole.UserRole)
                if folder_path:
                    self.delete_requested.emit(str(folder_path))
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _track_hover_item(self, item: QListWidgetItem):
        if item is not None:
            self.setCurrentItem(item)

    def _open_item(self, item: QListWidgetItem):
        folder_path = item.data(Qt.ItemDataRole.UserRole)
        if folder_path:
            self.open_requested.emit(str(folder_path))

    def _refresh_row_states(self):
        current_item = self.currentItem()
        for index in range(self.count()):
            item = self.item(index)
            row_widget = self.itemWidget(item)
            if isinstance(row_widget, RecentFolderRowWidget):
                row_widget.set_selected(item is current_item)

    def _sync_item_widths(self):
        viewport_width = max(0, self.viewport().width())
        if viewport_width <= 0:
            return
        for index in range(self.count()):
            item = self.item(index)
            row_widget = self.itemWidget(item)
            if item is None or row_widget is None:
                continue
            item.setSizeHint(QSize(viewport_width, row_widget.sizeHint().height()))


class RecentFolderRowWidget(QWidget):
    """One row in the recent-folders menu list."""

    open_requested = Signal(str)
    delete_requested = Signal(str)
    hover_requested = Signal(str)

    def __init__(self, folder_path: str, exists: bool, parent=None):
        super().__init__(parent)
        self.folder_path = str(folder_path)
        self._exists = bool(exists)
        self._selected = False
        self._delete_button_hovered = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._folder_label, self._parent_label = self._build_display_labels(self.folder_path)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(4)

        self.path_prefix_label = QLabel(self)
        self.path_prefix_label.setToolTip(self.folder_path)
        self.path_prefix_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )
        self.path_prefix_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.path_prefix_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.path_prefix_label.setWordWrap(False)
        self.path_prefix_label.setMargin(0)
        self.path_prefix_label.setIndent(0)
        self.path_prefix_label.setMouseTracking(True)
        self.path_prefix_label.installEventFilter(self)

        self.path_name_label = QLabel(self)
        self.path_name_label.setToolTip(self.folder_path)
        self.path_name_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )
        self.path_name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.path_name_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.path_name_label.setWordWrap(False)
        self.path_name_label.setMargin(0)
        self.path_name_label.setIndent(0)
        self.path_name_label.setMouseTracking(True)
        self.path_name_label.installEventFilter(self)

        self.delete_button = QToolButton(self)
        self.delete_button.setText("×")
        self.delete_button.setToolTip("Remove this folder from the recent list")
        self.delete_button.setAutoRaise(True)
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.delete_button.setMouseTracking(True)
        self.delete_button.installEventFilter(self)
        self.delete_button.clicked.connect(self._emit_delete_requested)
        self.delete_button.setFixedSize(16, 16)

        layout.addWidget(self.path_prefix_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.path_name_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row_height = max(28, self.sizeHint().height())
        self.setMinimumHeight(row_height)
        self.setMaximumHeight(row_height)
        self._apply_palette()

    def _request_hover(self):
        self.hover_requested.emit(self.folder_path)

    @classmethod
    def _build_display_labels(cls, folder_path: str) -> tuple[str, str]:
        """Return (folder_name, parent_path) for recent-folder rows."""
        try:
            path_obj = Path(folder_path)
            folder_name = path_obj.name or str(path_obj)
            parent_path = str(path_obj.parent) if str(path_obj.parent) not in {"", "."} else ""
        except Exception:
            folder_name = str(folder_path)
            parent_path = ""
        return folder_name, parent_path

    def enterEvent(self, event):
        self._request_hover()
        super().enterEvent(event)

    def mouseMoveEvent(self, event):
        self._request_hover()
        super().mouseMoveEvent(event)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if watched is self.delete_button:
            if event_type in (QEvent.Type.Enter, QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                self._request_hover()
                if not self._delete_button_hovered:
                    self._delete_button_hovered = True
                    self._apply_palette()
            elif event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                if self._delete_button_hovered:
                    self._delete_button_hovered = False
                    self._apply_palette()
        elif watched is self.path_prefix_label or watched is self.path_name_label:
            if event_type in (
                QEvent.Type.Enter,
                QEvent.Type.MouseMove,
                QEvent.Type.HoverMove,
            ):
                self._request_hover()
        return super().eventFilter(watched, event)

    def sizeHint(self):
        margins = self.layout().contentsMargins()
        prefix_height = self.path_prefix_label.sizeHint().height()
        name_height = self.path_name_label.sizeHint().height()
        row_height = max(prefix_height, name_height) + margins.top() + margins.bottom()
        row_width = max(0, self.layout().sizeHint().width())
        return QSize(row_width, row_height)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._request_hover()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.folder_path)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _emit_delete_requested(self):
        self.delete_requested.emit(self.folder_path)

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_palette()

    def _apply_palette(self):
        palette = self.palette()
        text_color = palette.color(QPalette.ColorRole.Text)
        highlight_text_color = palette.color(QPalette.ColorRole.HighlightedText)
        accent_color = palette.color(QPalette.ColorRole.Link)
        highlight_color = palette.color(QPalette.ColorRole.Highlight)

        name_color = highlight_text_color if self._selected else accent_color

        if self._selected:
            path_color = QColor(highlight_text_color)
        elif self._exists:
            path_color = palette.color(QPalette.ColorRole.PlaceholderText)
        else:
            path_color = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

        row_bg = QColor(highlight_color)
        row_bg.setAlpha(255 if self._selected else 0)
        if self._delete_button_hovered:
            delete_color = QColor(196, 64, 64)
            delete_color.setAlpha(230)
        else:
            delete_color = QColor(name_color if self._selected else text_color)
            delete_color.setAlpha(max(160, delete_color.alpha()))
        prefix_text, name_text = self._build_display_texts()

        self.setStyleSheet(
            "background-color: "
            f"{row_bg.name(QColor.NameFormat.HexArgb)};"
            "border: none;"
            "border-radius: 0px;"
        )
        self.path_prefix_label.setText(prefix_text)
        self.path_prefix_label.setStyleSheet(
            "QLabel {"
            f"color: {path_color.name(QColor.NameFormat.HexArgb)};"
            "background: transparent;"
            "padding: 0px;"
            "margin: 0px;"
            "}"
        )
        self.path_name_label.setText(name_text)
        self.path_name_label.setStyleSheet(
            "QLabel {"
            f"color: {name_color.name(QColor.NameFormat.HexArgb)};"
            "background: transparent;"
            "font-weight: 600;"
            "padding: 0px;"
            "margin: 0px;"
            "}"
        )
        self.delete_button.setStyleSheet(
            "QToolButton { border: none; padding: 0; margin: 0; background: transparent; "
            f"color: {delete_color.name(QColor.NameFormat.HexArgb)}; font-size: 14px; font-weight: 700; }}"
        )

    def _build_display_texts(self) -> tuple[str, str]:
        prefix = self._trim_middle_keep_root(self._parent_label, max_chars=44)
        separator = "\\" if "\\" in self.folder_path else "/"
        if prefix and not prefix.endswith(("/", "\\")):
            prefix = f"{prefix}{separator}"
        if not self._exists:
            prefix = f"{prefix}[missing] " if prefix else "[missing] "
        return prefix, self._folder_label

    @staticmethod
    def _trim_middle_keep_root(text: str, max_chars: int = 44) -> str:
        normalized = str(text or "").strip()
        if len(normalized) <= max_chars:
            return normalized

        separator = "\\" if "\\" in normalized else "/"
        root = ""
        remainder = normalized
        if separator == "\\" and len(normalized) >= 2 and normalized[1] == ":":
            root = normalized[:2] + separator
            remainder = normalized[2:].lstrip("\\/")
        elif normalized.startswith(separator):
            root = separator
            remainder = normalized.lstrip(separator)

        parts = [part for part in remainder.split(separator) if part]
        if not parts:
            return normalized

        tail_parts = parts[-2:] if len(parts) >= 2 else parts[-1:]
        tail = separator.join(tail_parts)
        trimmed = f"{root}...{separator}{tail}" if root else f"...{separator}{tail}"
        if len(trimmed) <= max_chars:
            return trimmed
        tail_keep = max(10, max_chars - len(root) - 4)
        return f"{root}...{tail[-tail_keep:]}" if root else f"...{tail[-tail_keep:]}"

class MenuManager:
    """Manages menu bar creation and setup."""

    def __init__(self, main_window):
        """Initialize menu manager."""
        self.main_window = main_window
        self.undo_action = None
        self.redo_action = None
        self.reload_directory_action = None
        self.refresh_new_media_only_action = None
        self.toggle_toolbar_action = None
        self.reset_toolbars_action = None
        self.reset_layout_action = None
        self.toggle_main_viewer_action = None
        self.toggle_image_list_action = None
        self.toggle_image_tags_editor_action = None
        self.toggle_all_tags_editor_action = None
        self.toggle_auto_captioner_action = None
        self.toggle_auto_markings_action = None
        self.toggle_perf_hud_action = None
        self.toggle_reaction_controls_action = None
        self.recent_folders_menu = None
        self.recent_folders_list_widget = None
        self.recent_folders_list_action = None
        self._recent_folders_preferred_path = None
        self.workspace_actions = {}
        self.workspace_action_group = None
        self.spawn_floating_viewer_action = None
        self.close_all_floating_viewers_action = None
        self.toggle_floating_hold_action = None
        self.menu_bar = None
        self.menu_strip = None
        self.menu_bar_right_host = None
        self.menu_bar_right_layout = None
        self.reaction_controls_widget = None
        self.rating_widget = None
        self.love_button = None
        self.bomb_button = None

    def create_menus(self):
        """Create and setup menu bar."""
        # Create actions first (needed before menu creation)
        self._create_actions()

        self.menu_strip = QWidget(self.main_window)
        strip_layout = QHBoxLayout(self.menu_strip)
        strip_layout.setContentsMargins(0, 0, 6, 0)
        strip_layout.setSpacing(4)

        menu_bar = QMenuBar(self.menu_strip)
        menu_bar.setNativeMenuBar(False)
        menu_bar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.menu_bar = menu_bar
        strip_layout.addWidget(menu_bar, stretch=0)
        strip_layout.addStretch(1)

        # File menu
        self._create_file_menu(menu_bar)

        # Edit menu
        self._create_edit_menu(menu_bar)

        # View menu
        self._create_view_menu(menu_bar)

        # Workspaces menu
        self._create_workspaces_menu(menu_bar)

        # Help menu
        self._create_help_menu(menu_bar)

        # Delete marked menu (hidden by default, shown when images are marked)
        self._create_delete_marked_menu(menu_bar)
        self._create_menu_bar_right_host(menu_bar)
        self.main_window.setMenuWidget(self.menu_strip)

    def _create_actions(self):
        """Create menu actions."""
        self.reload_directory_action = QAction('Reload Directory', parent=self.main_window)
        self.reload_directory_action.setDisabled(True)
        self.refresh_new_media_only_action = QAction('Refresh New Media Only', parent=self.main_window)
        self.refresh_new_media_only_action.setDisabled(True)
        self.undo_action = QAction('Undo', parent=self.main_window)
        self.redo_action = QAction('Redo', parent=self.main_window)
        self.toggle_toolbar_action = QAction('Toolbars', parent=self.main_window)
        self.reset_toolbars_action = QAction('Reset Toolbars', parent=self.main_window)
        self.reset_layout_action = QAction('Reset Layout', parent=self.main_window)
        self.toggle_main_viewer_action = QAction('Main Viewer', parent=self.main_window)
        self.toggle_image_list_action = QAction('Images', parent=self.main_window)
        self.toggle_image_tags_editor_action = QAction('Image Tags', parent=self.main_window)
        self.toggle_all_tags_editor_action = QAction('All Tags', parent=self.main_window)
        self.toggle_auto_captioner_action = QAction('Auto-Captioner', parent=self.main_window)
        self.toggle_auto_markings_action = QAction('Auto-Markings', parent=self.main_window)
        self.toggle_perf_hud_action = QAction('Performance HUD', parent=self.main_window)
        self.toggle_reaction_controls_action = QAction('Rating toolbar', parent=self.main_window)
        self.toggle_reaction_controls_action.setCheckable(True)
        self.spawn_floating_viewer_action = QAction('Spawn Floating Viewer', parent=self.main_window)
        self.close_all_floating_viewers_action = QAction('Close All Spawned Viewers', parent=self.main_window)
        self.toggle_floating_hold_action = QAction('Hold Existing Spawned Viewers', parent=self.main_window)
        self.toggle_floating_hold_action.setShortcut(QKeySequence('H'))
        self.delete_marked_menu = None
        self.delete_marked_button = None
        self.delete_marked_widget_action = None

    def _create_workspaces_menu(self, menu_bar):
        """Create Workspaces menu."""
        workspaces_menu = menu_bar.addMenu('Workspaces')

        presets = self.main_window.get_workspace_presets()
        self.workspace_action_group = QActionGroup(self.main_window)
        self.workspace_action_group.setExclusive(True)
        self.workspace_actions = {}

        shortcut_map = {
            'media_viewer': 'Alt+1',
            'tagging': 'Alt+2',
            'marking': 'Alt+3',
            'video_prep': 'Alt+4',
            'auto_captioning': 'Alt+5',
            'full_masonry': 'Alt+6',
        }

        for preset in presets:
            workspace_id = preset['id']
            label = preset['label']
            action = QAction(label, parent=self.main_window)
            action.setCheckable(True)
            if workspace_id in shortcut_map:
                action.setShortcut(QKeySequence(shortcut_map[workspace_id]))
            action.triggered.connect(
                lambda checked=False, wid=workspace_id: self.main_window.apply_workspace_preset(wid)
            )
            self.workspace_action_group.addAction(action)
            workspaces_menu.addAction(action)
            self.workspace_actions[workspace_id] = action

    def set_active_workspace(self, workspace_id: str):
        """Update checked workspace action."""
        if workspace_id in self.workspace_actions:
            self.workspace_actions[workspace_id].setChecked(True)

    def _create_file_menu(self, menu_bar):
        """Create File menu."""
        file_menu = menu_bar.addMenu('File')

        load_directory_action = QAction('Load Directory...', parent=self.main_window)
        load_directory_action.setShortcut(QKeySequence('Ctrl+L'))
        load_directory_action.triggered.connect(self.main_window.select_and_load_directory)
        file_menu.addAction(load_directory_action)

        self.reload_directory_action.setShortcuts(
            [QKeySequence('Ctrl+Shift+L'), QKeySequence('F5')])
        self.reload_directory_action.triggered.connect(self.main_window.reload_directory)
        file_menu.addAction(self.reload_directory_action)
        self.refresh_new_media_only_action.triggered.connect(self.main_window.refresh_new_media_only)
        file_menu.addAction(self.refresh_new_media_only_action)

        file_menu.addSeparator()

        self.recent_folders_menu = file_menu.addMenu('Recent Folders')
        self.recent_folders_menu.aboutToShow.connect(self._focus_recent_folders_list)
        self._update_recent_folders_menu()

        file_menu.addSeparator()

        export_action = QAction('Export...', parent=self.main_window)
        export_action.triggered.connect(self.main_window.export_images_dialog)
        file_menu.addAction(export_action)

        settings_action = QAction('Settings...', parent=self.main_window)
        settings_action.setShortcut(QKeySequence('Ctrl+Alt+S'))
        settings_action.triggered.connect(self.main_window.show_settings_dialog)
        file_menu.addAction(settings_action)

        exit_action = QAction('Exit', parent=self.main_window)
        exit_action.setShortcut(QKeySequence('Ctrl+W'))
        exit_action.triggered.connect(self.main_window.close)
        file_menu.addAction(exit_action)

    def _create_edit_menu(self, menu_bar):
        """Create Edit menu."""
        edit_menu = menu_bar.addMenu('Edit')

        self.undo_action.setShortcut(QKeySequence('Ctrl+Z'))
        self.undo_action.triggered.connect(self.main_window.image_list_model.undo)
        self.undo_action.setDisabled(True)
        edit_menu.addAction(self.undo_action)

        self.redo_action.setShortcut(QKeySequence('Ctrl+Y'))
        self.redo_action.triggered.connect(self.main_window.image_list_model.redo)
        self.redo_action.setDisabled(True)
        edit_menu.addAction(self.redo_action)

        edit_menu.addSeparator()

        # Video edit undo/redo
        undo_video_edit_action = QAction('Undo Video Edit', parent=self.main_window)
        undo_video_edit_action.setShortcut(QKeySequence('Ctrl+Shift+Z'))
        undo_video_edit_action.triggered.connect(
            lambda: self.main_window.video_editing_controller.undo_last_edit())
        edit_menu.addAction(undo_video_edit_action)

        redo_video_edit_action = QAction('Redo Video Edit', parent=self.main_window)
        redo_video_edit_action.setShortcut(QKeySequence('Ctrl+Shift+Y'))
        redo_video_edit_action.triggered.connect(
            lambda: self.main_window.video_editing_controller.redo_last_edit())
        edit_menu.addAction(redo_video_edit_action)

        edit_menu.addSeparator()

        find_and_replace_action = QAction('Find and Replace...', parent=self.main_window)
        find_and_replace_action.setShortcut(QKeySequence('Ctrl+R'))
        find_and_replace_action.triggered.connect(
            self.main_window.show_find_and_replace_dialog)
        edit_menu.addAction(find_and_replace_action)

        batch_reorder_tags_action = QAction('Batch Reorder Tags...', parent=self.main_window)
        batch_reorder_tags_action.setShortcut(QKeySequence('Ctrl+B'))
        batch_reorder_tags_action.triggered.connect(
            self.main_window.show_batch_reorder_tags_dialog)
        edit_menu.addAction(batch_reorder_tags_action)

        remove_duplicate_tags_action = QAction('Remove Duplicate Tags', parent=self.main_window)
        remove_duplicate_tags_action.triggered.connect(
            self.main_window.remove_duplicate_tags)
        edit_menu.addAction(remove_duplicate_tags_action)

        remove_empty_tags_action = QAction('Remove Empty Tags', parent=self.main_window)
        remove_empty_tags_action.triggered.connect(
            self.main_window.remove_empty_tags)
        edit_menu.addAction(remove_empty_tags_action)

    def _create_view_menu(self, menu_bar):
        """Create View menu."""
        view_menu = menu_bar.addMenu('View')

        self.toggle_toolbar_action.setCheckable(True)
        self.toggle_main_viewer_action.setCheckable(True)
        self.toggle_image_list_action.setCheckable(True)
        self.toggle_image_tags_editor_action.setCheckable(True)
        self.toggle_all_tags_editor_action.setCheckable(True)
        self.toggle_auto_captioner_action.setCheckable(True)
        self.toggle_auto_markings_action.setCheckable(True)
        self.toggle_perf_hud_action.setCheckable(True)

        # Connect toggle actions
        toolbar_manager = self.main_window.toolbar_manager
        self.toggle_toolbar_action.triggered.connect(
            lambda is_checked: toolbar_manager.set_toolbars_visible(is_checked))
        self.reset_toolbars_action.triggered.connect(
            self.main_window.reset_toolbar_layout
        )
        self.reset_layout_action.triggered.connect(
            self.main_window.reset_window_layout
        )
        self.toggle_main_viewer_action.triggered.connect(
            self.main_window.set_main_viewer_visible
        )
        self.toggle_image_list_action.triggered.connect(
            lambda is_checked: self.main_window.image_list.setVisible(is_checked))
        self.toggle_image_tags_editor_action.triggered.connect(
            lambda is_checked: self.main_window.image_tags_editor.setVisible(is_checked))
        self.toggle_all_tags_editor_action.triggered.connect(
            lambda is_checked: self.main_window.all_tags_editor.setVisible(is_checked))
        self.toggle_auto_captioner_action.triggered.connect(
            lambda is_checked: self.main_window.auto_captioner.setVisible(is_checked))
        self.toggle_auto_markings_action.triggered.connect(
            lambda is_checked: self.main_window.auto_markings.setVisible(is_checked))
        self.toggle_perf_hud_action.triggered.connect(
            lambda checked: self.main_window.set_perf_hud_visible(checked)
        )

        view_menu.addAction(self.toggle_toolbar_action)
        toolbar_groups_menu = view_menu.addMenu('Toolbar Groups')
        for toolbar in toolbar_manager.get_toolbars():
            if str(toolbar.property('toolbar_group_key') or '') == 'rating':
                self.toggle_reaction_controls_action.triggered.connect(
                    self.main_window.set_reaction_controls_panel_visible
                )
                toolbar_groups_menu.addAction(self.toggle_reaction_controls_action)
            else:
                action = toolbar.toggleViewAction()
                action.setText(toolbar.windowTitle())
                toolbar_groups_menu.addAction(action)
        view_menu.addAction(self.reset_toolbars_action)
        view_menu.addAction(self.reset_layout_action)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_main_viewer_action)
        view_menu.addAction(self.toggle_image_list_action)
        view_menu.addAction(self.toggle_image_tags_editor_action)
        view_menu.addAction(self.toggle_all_tags_editor_action)
        view_menu.addAction(self.toggle_auto_captioner_action)
        view_menu.addAction(self.toggle_auto_markings_action)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_perf_hud_action)

        self.spawn_floating_viewer_action.setShortcut(QKeySequence('Ctrl+Shift+N'))
        self.spawn_floating_viewer_action.triggered.connect(
            self.main_window.spawn_floating_viewer)
        self.close_all_floating_viewers_action.setShortcut(QKeySequence('Ctrl+Shift+W'))
        self.close_all_floating_viewers_action.triggered.connect(
            self.main_window.close_all_floating_viewers)
        self.toggle_floating_hold_action.setCheckable(True)
        self.toggle_floating_hold_action.triggered.connect(
            lambda checked: self.main_window.set_floating_hold_mode(checked)
        )

        view_menu.addSeparator()
        view_menu.addAction(self.toggle_floating_hold_action)
        view_menu.addAction(self.spawn_floating_viewer_action)
        view_menu.addAction(self.close_all_floating_viewers_action)

    def _create_help_menu(self, menu_bar):
        """Create Help menu."""
        help_menu = menu_bar.addMenu('Help')
        open_documentation_hub_action = QAction(
            'Documentation Hub', parent=self.main_window
        )
        open_documentation_hub_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(DOCUMENTATION_HUB_URL))
        )
        help_menu.addAction(open_documentation_hub_action)

        open_github_repository_action = QAction(
            'GitHub Repository', parent=self.main_window
        )
        open_github_repository_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_REPOSITORY_URL)))
        help_menu.addAction(open_github_repository_action)
        help_menu.addSeparator()

        about_action = QAction(
            f'About {APP_DISPLAY_NAME}', parent=self.main_window
        )
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _show_about_dialog(self):
        """Show application metadata and entry points."""
        about_box = QMessageBox(self.main_window)
        about_box.setWindowTitle(f'About {APP_DISPLAY_NAME}')
        about_box.setIcon(QMessageBox.Icon.Information)
        about_box.setTextFormat(Qt.TextFormat.RichText)
        about_box.setText(
            f'<b>{APP_DISPLAY_NAME}</b><br>'
            f'Version {__version__}'
        )
        about_box.setInformativeText(
            'Desktop app for browsing, tagging, captioning, and reviewing large '
            'image and video datasets.<br><br>'
            f'Documentation Hub:<br><a href="{DOCUMENTATION_HUB_URL}">{DOCUMENTATION_HUB_URL}</a><br><br>'
            f'GitHub Repository:<br><a href="{GITHUB_REPOSITORY_URL}">{GITHUB_REPOSITORY_URL}</a>'
        )
        about_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        about_box.exec()

    def update_undo_and_redo_actions(self):
        """Update undo/redo menu action text and enabled state."""
        if self.main_window.image_list_model.undo_stack:
            undo_action_name = self.main_window.image_list_model.undo_stack[-1].action_name
            self.undo_action.setText(f'Undo "{undo_action_name}"')
            self.undo_action.setDisabled(False)
        else:
            self.undo_action.setText('Undo')
            self.undo_action.setDisabled(True)

        if self.main_window.image_list_model.redo_stack:
            redo_action_name = self.main_window.image_list_model.redo_stack[-1].action_name
            self.redo_action.setText(f'Redo "{redo_action_name}"')
            self.redo_action.setDisabled(False)
        else:
            self.redo_action.setText('Redo')
            self.redo_action.setDisabled(True)

    def _update_recent_folders_menu(self):
        """Update recent folders menu with current list."""
        self.recent_folders_menu.clear()
        recent_dirs = settings.value(
            'recent_directories',
            defaultValue=DEFAULT_SETTINGS['recent_directories'],
            type=list
        )
        if not isinstance(recent_dirs, list):
            recent_dirs = []

        if not recent_dirs:
            no_recent_action = QAction('No recent folders', self.main_window)
            no_recent_action.setEnabled(False)
            self.recent_folders_menu.addAction(no_recent_action)
            return

        container = QWidget(self.recent_folders_menu)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.recent_folders_list_widget = RecentFoldersListWidget(container)
        self.recent_folders_list_widget.open_requested.connect(self._open_recent_folder)
        self.recent_folders_list_widget.delete_requested.connect(self._remove_recent_folder)

        self.recent_folders_list_widget.setMinimumWidth(520)

        for dir_path in recent_dirs:
            folder_path = str(dir_path)
            exists = Path(folder_path).exists()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, folder_path)
            self.recent_folders_list_widget.addItem(item)
            row_widget = RecentFolderRowWidget(folder_path, exists, self.recent_folders_list_widget)
            row_widget.open_requested.connect(self._open_recent_folder)
            row_widget.delete_requested.connect(self._remove_recent_folder)
            row_widget.hover_requested.connect(self._set_current_recent_folder)
            item_height = row_widget.sizeHint().height()
            item.setSizeHint(QSize(0, item_height))
            self.recent_folders_list_widget.setItemWidget(item, row_widget)

        self.recent_folders_list_widget._sync_item_widths()

        visible_count = min(10, len(recent_dirs))
        row_height = max(24, self.recent_folders_list_widget.sizeHintForRow(0))
        if row_height <= 0:
            row_height = 24
        list_height = (row_height * visible_count) + 4
        self.recent_folders_list_widget.setMinimumHeight(list_height)
        self.recent_folders_list_widget.setMaximumHeight(list_height)

        layout.addWidget(self.recent_folders_list_widget)
        self.recent_folders_list_action = QWidgetAction(self.recent_folders_menu)
        self.recent_folders_list_action.setDefaultWidget(container)
        self.recent_folders_menu.addAction(self.recent_folders_list_action)

        self.recent_folders_menu.addSeparator()
        clear_action = QAction('Clear Recent Folders', self.main_window)
        clear_action.triggered.connect(self._clear_recent_folders)
        self.recent_folders_menu.addAction(clear_action)

    def _clear_recent_folders(self):
        """Clear the recent folders list."""
        settings.setValue('recent_directories', [])
        self._update_recent_folders_menu()

    def _focus_recent_folders_list(self):
        """Keep the embedded list keyboard-active while the menu is open."""
        if self.recent_folders_list_widget is None:
            return
        self.recent_folders_list_widget.setFocus()
        preferred = str(getattr(self, '_recent_folders_preferred_path', '') or '').strip()
        if preferred:
            for row in range(self.recent_folders_list_widget.count()):
                item = self.recent_folders_list_widget.item(row)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == preferred:
                    self.recent_folders_list_widget.setCurrentRow(row)
                    return
        if self.recent_folders_list_widget.count() > 0:
            self.recent_folders_list_widget.setCurrentRow(0)

    def _open_recent_folder(self, dir_path: str):
        """Open a folder from the embedded recent-folders list."""
        folder_path = Path(dir_path)
        if not folder_path.exists():
            self._remove_recent_folder(dir_path)
            return
        self.recent_folders_menu.hide()
        self.main_window.load_directory(folder_path, save_path_to_settings=True)

    def _set_current_recent_folder(self, dir_path: str):
        """Highlight a recent-folder row by path."""
        if self.recent_folders_list_widget is None:
            return
        target_path = str(dir_path)
        for row in range(self.recent_folders_list_widget.count()):
            item = self.recent_folders_list_widget.item(row)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == target_path:
                self.recent_folders_list_widget.setCurrentRow(row)
                return

    def _remove_recent_folder(self, dir_path: str):
        """Remove one folder from the persisted recent-folders list."""
        recent_dirs = settings.value(
            'recent_directories',
            defaultValue=DEFAULT_SETTINGS['recent_directories'],
            type=list,
        )
        if not isinstance(recent_dirs, list):
            recent_dirs = []
        target_path = str(dir_path)
        removal_index = -1
        for idx, entry in enumerate(recent_dirs):
            if str(entry) == target_path:
                removal_index = idx
                break
        updated_dirs = [entry for entry in recent_dirs if str(entry) != target_path]
        preferred_path = None
        if updated_dirs:
            fallback_index = max(0, min(removal_index, len(updated_dirs) - 1))
            preferred_path = str(updated_dirs[fallback_index])
        self._recent_folders_preferred_path = preferred_path
        settings.setValue('recent_directories', updated_dirs)
        self._update_recent_folders_menu()
        if self.recent_folders_menu.isVisible():
            QTimer.singleShot(0, self._focus_recent_folders_list)

    def _create_delete_marked_menu(self, menu_bar):
        """Create Delete Marked menu (shown only when images are marked)."""
        # Create a custom button
        self.delete_marked_button = QPushButton('🗑️ Delete Marked', menu_bar)
        self.delete_marked_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e53e3e, stop:1 #c53030);
                color: white;
                border: 1px solid rgba(0, 0, 0, 0.2);
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 500;
                margin: 2px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fc8181, stop:1 #e53e3e);
                border: 1px solid rgba(0, 0, 0, 0.3);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #c53030, stop:1 #9b2c2c);
                border: 1px solid rgba(0, 0, 0, 0.4);
            }
            QPushButton::menu-indicator {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 12px;
                right: 8px;
            }
        """)

        # Create the dropdown menu
        from PySide6.QtWidgets import QMenu
        self.delete_marked_menu = QMenu(self.main_window)

        delete_all_action = QAction('Delete All Marked Images', parent=self.main_window)
        delete_all_action.triggered.connect(self._delete_all_marked)
        self.delete_marked_menu.addAction(delete_all_action)

        unmark_all_action = QAction('Unmark All Images', parent=self.main_window)
        unmark_all_action.triggered.connect(self._unmark_all_images)
        self.delete_marked_menu.addAction(unmark_all_action)

        # Attach menu to button
        self.delete_marked_button.setMenu(self.delete_marked_menu)
        self.delete_marked_button.setVisible(False)
        self._refresh_menu_bar_right_host_visibility()

    def _create_menu_bar_right_host(self, menu_bar: QMenuBar):
        """Create one top-right host for persistent menu-row widgets."""
        host = QWidget(self.menu_strip)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(8, 2, 0, 2)
        layout.setSpacing(8)
        host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        toolbar_manager = getattr(self.main_window, 'toolbar_manager', None)
        if toolbar_manager is not None:
            self.reaction_controls_widget = toolbar_manager.create_reaction_controls_widget(
                overlay_mode=False,
                compact_mode=True,
                parent=host,
            )
            self.rating_widget = self.reaction_controls_widget.rating_widget
            self.love_button = self.reaction_controls_widget.love_button
            self.bomb_button = self.reaction_controls_widget.bomb_button
            layout.addWidget(self.reaction_controls_widget)

        if self.delete_marked_button is not None:
            self.delete_marked_button.setParent(host)
            layout.addWidget(self.delete_marked_button)

        self.menu_bar_right_host = host
        self.menu_bar_right_layout = layout
        if self.menu_strip is not None and self.menu_strip.layout() is not None:
            self.menu_strip.layout().addWidget(host, stretch=0)
        host.adjustSize()
        host.setMinimumWidth(max(host.sizeHint().width(), host.minimumSizeHint().width()))
        self._refresh_menu_bar_right_host_visibility()

    def set_reaction_controls_visible(self, visible: bool):
        widget = getattr(self, 'reaction_controls_widget', None)
        if widget is not None:
            widget.setVisible(bool(visible))
        action = getattr(self, 'toggle_reaction_controls_action', None)
        if action is not None:
            blocker = action.blockSignals(True)
            action.setChecked(bool(visible))
            action.blockSignals(blocker)
        self._refresh_menu_bar_right_host_visibility()

    def position_menu_bar_right_host(self):
        return

    def _refresh_menu_bar_right_host_visibility(self):
        host = getattr(self, 'menu_bar_right_host', None)
        if host is None:
            return
        reaction_visible = bool(
            getattr(self, 'reaction_controls_widget', None)
            and not self.reaction_controls_widget.isHidden()
        )
        delete_visible = bool(
            getattr(self, 'delete_marked_button', None)
            and not self.delete_marked_button.isHidden()
        )
        host.setVisible(reaction_visible or delete_visible)
        if host.isVisible():
            QTimer.singleShot(0, self.position_menu_bar_right_host)

    def _delete_all_marked(self):
        """Delete all marked images."""
        if hasattr(self.main_window, 'image_list'):
            self.main_window.image_list.delete_marked_images()

    def _unmark_all_images(self):
        """Unmark all images marked for deletion."""
        if hasattr(self.main_window, 'image_list'):
            self.main_window.image_list.unmark_all_images()

    def update_delete_marked_menu(self, count):
        """Update delete marked menu visibility and text."""
        if self.delete_marked_button:
            self.delete_marked_button.setVisible(count > 0)
            if count > 0:
                self.delete_marked_button.setText(f'🗑️ Delete Marked ({count})')
            self._refresh_menu_bar_right_host_visibility()
