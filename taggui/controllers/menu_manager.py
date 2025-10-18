"""Manager for main window menu bar."""

from PySide6.QtWidgets import QMenuBar
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices
from PySide6.QtCore import QUrl


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

        # Help menu
        self._create_help_menu(menu_bar)

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
