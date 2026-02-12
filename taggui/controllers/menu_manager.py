"""Manager for main window menu bar."""

from pathlib import Path
from PySide6.QtWidgets import QMenuBar, QPushButton, QWidgetAction
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QDesktopServices
from PySide6.QtCore import QUrl

from utils.settings import settings, DEFAULT_SETTINGS


class MenuManager:
    """Manages menu bar creation and setup."""

    def __init__(self, main_window):
        """Initialize menu manager."""
        self.main_window = main_window
        self.undo_action = None
        self.redo_action = None
        self.reload_directory_action = None
        self.toggle_toolbar_action = None
        self.toggle_image_list_action = None
        self.toggle_image_tags_editor_action = None
        self.toggle_all_tags_editor_action = None
        self.toggle_auto_captioner_action = None
        self.toggle_auto_markings_action = None
        self.recent_folders_menu = None
        self.workspace_actions = {}
        self.workspace_action_group = None
        self.spawn_floating_viewer_action = None
        self.close_all_floating_viewers_action = None

    def create_menus(self):
        """Create and setup menu bar."""
        # Create actions first (needed before menu creation)
        self._create_actions()

        menu_bar = self.main_window.menuBar()

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

    def _create_actions(self):
        """Create menu actions."""
        self.reload_directory_action = QAction('Reload Directory', parent=self.main_window)
        self.reload_directory_action.setDisabled(True)
        self.undo_action = QAction('Undo', parent=self.main_window)
        self.redo_action = QAction('Redo', parent=self.main_window)
        self.toggle_toolbar_action = QAction('Toolbar', parent=self.main_window)
        self.toggle_image_list_action = QAction('Images', parent=self.main_window)
        self.toggle_image_tags_editor_action = QAction('Image Tags', parent=self.main_window)
        self.toggle_all_tags_editor_action = QAction('All Tags', parent=self.main_window)
        self.toggle_auto_captioner_action = QAction('Auto-Captioner', parent=self.main_window)
        self.toggle_auto_markings_action = QAction('Auto-Markings', parent=self.main_window)
        self.spawn_floating_viewer_action = QAction('Spawn Floating Viewer', parent=self.main_window)
        self.close_all_floating_viewers_action = QAction('Close Floating Viewers', parent=self.main_window)
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

        file_menu.addSeparator()

        self.recent_folders_menu = file_menu.addMenu('Recent Folders')
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
        remove_duplicate_tags_action.setShortcut(QKeySequence('Ctrl+D'))
        remove_duplicate_tags_action.triggered.connect(
            self.main_window.remove_duplicate_tags)
        edit_menu.addAction(remove_duplicate_tags_action)

        remove_empty_tags_action = QAction('Remove Empty Tags', parent=self.main_window)
        remove_empty_tags_action.setShortcut(QKeySequence('Ctrl+E'))
        remove_empty_tags_action.triggered.connect(
            self.main_window.remove_empty_tags)
        edit_menu.addAction(remove_empty_tags_action)

    def _create_view_menu(self, menu_bar):
        """Create View menu."""
        view_menu = menu_bar.addMenu('View')

        self.toggle_toolbar_action.setCheckable(True)
        self.toggle_image_list_action.setCheckable(True)
        self.toggle_image_tags_editor_action.setCheckable(True)
        self.toggle_all_tags_editor_action.setCheckable(True)
        self.toggle_auto_captioner_action.setCheckable(True)
        self.toggle_auto_markings_action.setCheckable(True)

        # Connect toggle actions
        toolbar_manager = self.main_window.toolbar_manager
        self.toggle_toolbar_action.triggered.connect(
            lambda is_checked: toolbar_manager.toolbar.setVisible(is_checked))
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

        view_menu.addAction(self.toggle_toolbar_action)
        view_menu.addAction(self.toggle_image_list_action)
        view_menu.addAction(self.toggle_image_tags_editor_action)
        view_menu.addAction(self.toggle_all_tags_editor_action)
        view_menu.addAction(self.toggle_auto_captioner_action)
        view_menu.addAction(self.toggle_auto_markings_action)

        self.spawn_floating_viewer_action.setShortcut(QKeySequence('Ctrl+Shift+N'))
        self.spawn_floating_viewer_action.triggered.connect(
            self.main_window.spawn_floating_viewer)
        self.close_all_floating_viewers_action.setShortcut(QKeySequence('Ctrl+Shift+W'))
        self.close_all_floating_viewers_action.triggered.connect(
            self.main_window.close_all_floating_viewers)

        view_menu.addSeparator()
        view_menu.addAction(self.spawn_floating_viewer_action)
        view_menu.addAction(self.close_all_floating_viewers_action)

    def _create_help_menu(self, menu_bar):
        """Create Help menu."""
        help_menu = menu_bar.addMenu('Help')
        GITHUB_REPOSITORY_URL = 'https://github.com/jhc13/taggui'
        open_github_repository_action = QAction('GitHub', parent=self.main_window)
        open_github_repository_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_REPOSITORY_URL)))
        help_menu.addAction(open_github_repository_action)

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

        if not recent_dirs:
            no_recent_action = QAction('No recent folders', self.main_window)
            no_recent_action.setEnabled(False)
            self.recent_folders_menu.addAction(no_recent_action)
            return

        for dir_path in recent_dirs:
            if Path(dir_path).exists():
                action = QAction(dir_path, self.main_window)
                action.triggered.connect(
                    lambda checked=False, p=dir_path:
                        self.main_window.load_directory(Path(p), save_path_to_settings=True)
                )
                self.recent_folders_menu.addAction(action)

        self.recent_folders_menu.addSeparator()
        clear_action = QAction('Clear Recent Folders', self.main_window)
        clear_action.triggered.connect(self._clear_recent_folders)
        self.recent_folders_menu.addAction(clear_action)

    def _clear_recent_folders(self):
        """Clear the recent folders list."""
        settings.setValue('recent_directories', [])
        self._update_recent_folders_menu()

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

        # Position button manually after Help menu
        # Get the Help menu position
        help_action = None
        for action in menu_bar.actions():
            if 'Help' in action.text():
                help_action = action
                break

        if help_action:
            # Get Help menu's geometry
            help_rect = menu_bar.actionGeometry(help_action)
            # Position button right after Help menu
            self.delete_marked_button.setGeometry(
                help_rect.right() + 5,
                help_rect.top(),
                self.delete_marked_button.sizeHint().width(),
                help_rect.height()
            )

        # Show/hide based on marked count
        self.delete_marked_button.setVisible(False)

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
                # Re-position in case window was resized
                menu_bar = self.main_window.menuBar()
                help_action = None
                for action in menu_bar.actions():
                    if 'Help' in action.text():
                        help_action = action
                        break
                if help_action:
                    help_rect = menu_bar.actionGeometry(help_action)
                    self.delete_marked_button.setGeometry(
                        help_rect.right() + 5,
                        help_rect.top(),
                        self.delete_marked_button.sizeHint().width(),
                        help_rect.height()
                    )
