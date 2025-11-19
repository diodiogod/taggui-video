from pathlib import Path

from PySide6.QtCore import QKeyCombination, QModelIndex, QUrl, Qt, QTimer, Slot
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QDesktopServices,
                           QIcon, QKeySequence, QShortcut, QMouseEvent)
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow,
                               QMessageBox, QStackedWidget, QToolBar,
                               QVBoxLayout, QWidget, QSizePolicy, QHBoxLayout,
                               QLabel, QPushButton)

from transformers import AutoTokenizer

from controllers.video_editing_controller import VideoEditingController
from controllers.toolbar_manager import ToolbarManager
from controllers.menu_manager import MenuManager
from controllers.signal_manager import SignalManager
from dialogs.batch_reorder_tags_dialog import BatchReorderTagsDialog
from dialogs.find_and_replace_dialog import FindAndReplaceDialog
from dialogs.export_dialog import ExportDialog
from dialogs.settings_dialog import SettingsDialog
from models.image_list_model import ImageListModel
from models.image_tag_list_model import ImageTagListModel
from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.icons import taggui_icon
from utils.big_widgets import BigPushButton
from utils.image import Image
from utils.key_press_forwarder import KeyPressForwarder
from utils.settings import DEFAULT_SETTINGS, settings, get_tag_separator
from utils.shortcut_remover import ShortcutRemover
from utils.utils import get_resource_path, pluralize
from widgets.all_tags_editor import AllTagsEditor
from widgets.auto_captioner import AutoCaptioner
from widgets.auto_markings import AutoMarkings
from widgets.image_list import ImageList
from widgets.image_tags_editor import ImageTagsEditor
from widgets.image_viewer import ImageViewer

TOKENIZER_DIRECTORY_PATH = Path('clip-vit-base-patch32')


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.directory_path = None
        self.is_running = True
        app.aboutToQuit.connect(lambda: setattr(self, 'is_running', False))

        # Initialize models
        image_list_image_width = settings.value(
            'image_list_image_width',
            defaultValue=DEFAULT_SETTINGS['image_list_image_width'], type=int)
        tag_separator = get_tag_separator()
        self.image_list_model = ImageListModel(image_list_image_width, tag_separator)
        tokenizer = AutoTokenizer.from_pretrained(get_resource_path(TOKENIZER_DIRECTORY_PATH))
        self.proxy_image_list_model = ProxyImageListModel(
            self.image_list_model, tokenizer, tag_separator)
        self.image_list_model.proxy_image_list_model = self.proxy_image_list_model
        self.tag_counter_model = TagCounterModel()
        self.image_tag_list_model = ImageTagListModel()

        # Initialize controllers and managers
        self.video_editing_controller = VideoEditingController(self)
        self.toolbar_manager = ToolbarManager(self)
        self.menu_manager = MenuManager(self)
        self.signal_manager = SignalManager(self)

        # Setup window
        self.setWindowIcon(taggui_icon())
        self.setPalette(self.app.style().standardPalette())
        self.set_font_size()
        self.image_viewer = ImageViewer(self.proxy_image_list_model)
        self.create_central_widget()

        # Create toolbar and menus
        self.toolbar_manager.create_toolbar()
        self.rating = self.toolbar_manager.rating
        self.star_labels = self.toolbar_manager.star_labels

        self.image_list = ImageList(self.proxy_image_list_model,
                                    tag_separator, image_list_image_width)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self.image_list)
        self.image_tags_editor = ImageTagsEditor(
            self.proxy_image_list_model, self.tag_counter_model,
            self.image_tag_list_model, self.image_list, tokenizer,
            tag_separator)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.image_tags_editor)
        self.all_tags_editor = AllTagsEditor(self.tag_counter_model)
        self.tag_counter_model.all_tags_list = (self.all_tags_editor
                                                .all_tags_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.all_tags_editor)
        self.auto_captioner = AutoCaptioner(self.image_list_model,
                                            self.image_list, self.image_viewer)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.auto_captioner)
        self.auto_markings = AutoMarkings(self.image_list_model,
                                          self.image_list, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.auto_markings)
        self.tabifyDockWidget(self.all_tags_editor, self.auto_captioner)
        self.tabifyDockWidget(self.auto_captioner, self.auto_markings)
        self.all_tags_editor.raise_()
        # Set default widths for the dock widgets.
        # Temporarily set a size for the window so that the dock widgets can be
        # expanded to their default widths. If the window geometry was
        # previously saved, it will be restored later.
        self.resize(image_list_image_width * 8,
                    int(image_list_image_width * 4.5))
        self.resizeDocks([self.image_list, self.image_tags_editor,
                          self.all_tags_editor],
                         [int(image_list_image_width * 2.5)] * 3,
                         Qt.Orientation.Horizontal)
        # Disable some widgets until a directory is loaded
        self.image_tags_editor.tag_input_box.setDisabled(True)
        self.auto_captioner.start_cancel_button.setDisabled(True)

        # Create menus
        self.menu_manager.create_menus()

        # Setup image list selection model
        self.image_list_selection_model = self.image_list.list_view.selectionModel()
        self.image_list_model.image_list_selection_model = self.image_list_selection_model

        # Connect all signals
        self.signal_manager.connect_all_signals()
        # Forward any unhandled image changing key presses to the image list.
        key_press_forwarder = KeyPressForwarder(
            parent=self, target=self.image_list.list_view,
            keys_to_forward=(Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp,
                             Qt.Key.Key_PageDown, Qt.Key.Key_Home,
                             Qt.Key.Key_End))
        self.installEventFilter(key_press_forwarder)
        # Remove the Ctrl+Z shortcut from text input boxes to prevent it from
        # conflicting with the undo action.
        ctrl_z = QKeyCombination(Qt.KeyboardModifier.ControlModifier,
                                 key=Qt.Key.Key_Z)
        ctrl_y = QKeyCombination(Qt.KeyboardModifier.ControlModifier,
                                 key=Qt.Key.Key_Y)
        shortcut_remover = ShortcutRemover(parent=self,
                                           shortcuts=(ctrl_z, ctrl_y))
        self.image_list.filter_line_edit.installEventFilter(shortcut_remover)
        self.image_tags_editor.tag_input_box.installEventFilter(
            shortcut_remover)
        self.all_tags_editor.filter_line_edit.installEventFilter(
            shortcut_remover)
        # Set keyboard shortcuts.
        focus_filter_images_box_shortcut = QShortcut(
            QKeySequence('Alt+F'), self)
        focus_filter_images_box_shortcut.activated.connect(
            self.image_list.raise_)
        focus_filter_images_box_shortcut.activated.connect(
            self.image_list.filter_line_edit.setFocus)
        focus_add_tag_box_shortcut = QShortcut(QKeySequence('Alt+A'), self)
        focus_add_tag_box_shortcut.activated.connect(
            self.image_tags_editor.raise_)
        focus_add_tag_box_shortcut.activated.connect(
            self.image_tags_editor.tag_input_box.setFocus)
        focus_image_tags_list_shortcut = QShortcut(QKeySequence('Alt+I'), self)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.raise_)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.image_tags_list.setFocus)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.select_first_tag)
        focus_search_tags_box_shortcut = QShortcut(QKeySequence('Alt+S'), self)
        focus_search_tags_box_shortcut.activated.connect(
            self.all_tags_editor.raise_)
        focus_search_tags_box_shortcut.activated.connect(
            self.all_tags_editor.filter_line_edit.setFocus)
        focus_caption_button_shortcut = QShortcut(QKeySequence('Alt+C'), self)
        focus_caption_button_shortcut.activated.connect(
            self.auto_captioner.raise_)
        focus_caption_button_shortcut.activated.connect(
            self.auto_captioner.start_cancel_button.setFocus)
        go_to_previous_image_shortcut = QShortcut(QKeySequence('Ctrl+Up'),
                                                  self)
        go_to_previous_image_shortcut.activated.connect(
            self.image_list.go_to_previous_image)
        go_to_next_image_shortcut = QShortcut(QKeySequence('Ctrl+Down'), self)
        go_to_next_image_shortcut.activated.connect(
            self.image_list.go_to_next_image)
        jump_to_first_untagged_image_shortcut = QShortcut(
            QKeySequence('Ctrl+J'), self)
        jump_to_first_untagged_image_shortcut.activated.connect(
            self.image_list.jump_to_first_untagged_image)
        self.restore()
        self.image_tags_editor.tag_input_box.setFocus()

        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self.delayed_filter)
        self._filter_delay = 100
        self._max_delay = 500
        self._filter_timer_running = False

    def closeEvent(self, event: QCloseEvent):
        """Save the window geometry and state before closing."""
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('window_state', self.saveState())
        # Save marker size setting
        settings.setValue('fixed_marker_size', self.toolbar_manager.fixed_marker_size_spinbox.value())
        super().closeEvent(event)

    def set_font_size(self):
        font = self.app.font()
        font_size = settings.value(
            'font_size', defaultValue=DEFAULT_SETTINGS['font_size'], type=int)
        font.setPointSize(font_size)
        self.app.setFont(font)

    def create_central_widget(self):
        central_widget = QStackedWidget()
        # Put the button inside a widget so that it will not fill up the entire
        # space.
        load_directory_widget = QWidget()
        load_directory_button = BigPushButton('Load Directory...')
        load_directory_button.clicked.connect(self.select_and_load_directory)
        QVBoxLayout(load_directory_widget).addWidget(
            load_directory_button, alignment=Qt.AlignmentFlag.AlignCenter)
        central_widget.addWidget(load_directory_widget)
        central_widget.addWidget(self.image_viewer)
        self.setCentralWidget(central_widget)

    @Slot()
    def zoom(self, factor):
        toolbar_mgr = self.toolbar_manager
        if factor < 0:
            toolbar_mgr.zoom_fit_best_action.setChecked(True)
            toolbar_mgr.zoom_original_action.setChecked(False)
        elif factor == 1.0:
            toolbar_mgr.zoom_fit_best_action.setChecked(False)
            toolbar_mgr.zoom_original_action.setChecked(True)
        else:
            toolbar_mgr.zoom_fit_best_action.setChecked(False)
            toolbar_mgr.zoom_original_action.setChecked(False)

    def load_directory(self, path: Path, select_index: int = 0,
                       save_path_to_settings: bool = False):
        self.directory_path = path.resolve()
        if save_path_to_settings:
            settings.setValue('directory_path', str(self.directory_path))
            self._add_to_recent_directories(str(self.directory_path))
        self.setWindowTitle(path.name)
        self.image_list_model.load_directory(path)
        self.image_list.filter_line_edit.clear()
        self.all_tags_editor.filter_line_edit.clear()
        # Clear the current index first to make sure that the `currentChanged`
        # signal is emitted even if the image at the index is already selected.
        self.image_list_selection_model.clearCurrentIndex()
        self.image_list.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(select_index, 0))
        self.centralWidget().setCurrentWidget(self.image_viewer)
        self.menu_manager.reload_directory_action.setDisabled(False)
        self.image_tags_editor.tag_input_box.setDisabled(False)
        self.auto_captioner.start_cancel_button.setDisabled(False)

    @Slot()
    def select_and_load_directory(self):
        initial_directory = (str(self.directory_path)
                             if self.directory_path else '')
        load_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory to load images from',
            dir=initial_directory)
        if not load_directory_path:
            return
        self.load_directory(Path(load_directory_path),
                            save_path_to_settings=True)

    @Slot()
    def reload_directory(self):
        # Save the filter text and the index of the selected image to restore
        # them after reloading the directory.
        filter_text = self.image_list.filter_line_edit.text()
        select_index_key = ('image_index'
                            if self.proxy_image_list_model.filter is None
                            else 'filtered_image_index')
        select_index = settings.value(select_index_key, type=int) or 0
        self.load_directory(self.directory_path)
        self.image_list.filter_line_edit.setText(filter_text)
        # If the selected image index is out of bounds due to images being
        # deleted, select the last image.
        if select_index >= self.proxy_image_list_model.rowCount():
            select_index = self.proxy_image_list_model.rowCount() - 1
        self.image_list.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(select_index, 0))

    @Slot()
    def export_images_dialog(self):
        export_dialog = ExportDialog(parent=self, image_list=self.image_list)
        export_dialog.exec()
        return

    @Slot()
    def show_settings_dialog(self):
        settings_dialog = SettingsDialog(parent=self)
        settings_dialog.exec()

    @Slot()
    def show_find_and_replace_dialog(self):
        find_and_replace_dialog = FindAndReplaceDialog(
            parent=self, image_list_model=self.image_list_model)
        find_and_replace_dialog.exec()

    @Slot()
    def show_batch_reorder_tags_dialog(self):
        batch_reorder_tags_dialog = BatchReorderTagsDialog(
            parent=self, image_list_model=self.image_list_model,
            tag_counter_model=self.tag_counter_model)
        batch_reorder_tags_dialog.exec()

    @Slot()
    def remove_duplicate_tags(self):
        removed_tag_count = self.image_list_model.remove_duplicate_tags()
        message_box = QMessageBox()
        message_box.setWindowTitle('Remove Duplicate Tags')
        message_box.setIcon(QMessageBox.Icon.Information)
        if not removed_tag_count:
            text = 'No duplicate tags were found.'
        else:
            text = (f'Removed {removed_tag_count} duplicate '
                    f'{pluralize("tag", removed_tag_count)}.')
        message_box.setText(text)
        message_box.exec()

    @Slot()
    def remove_empty_tags(self):
        removed_tag_count = self.image_list_model.remove_empty_tags()
        message_box = QMessageBox()
        message_box.setWindowTitle('Remove Empty Tags')
        message_box.setIcon(QMessageBox.Icon.Information)
        if not removed_tag_count:
            text = 'No empty tags were found.'
        else:
            text = (f'Removed {removed_tag_count} empty '
                    f'{pluralize("tag", removed_tag_count)}.')
        message_box.setText(text)
        message_box.exec()


    @Slot()
    def set_image_list_filter(self):
        if self._filter_timer.isActive():
            self._filter_timer.stop()
        
        if hasattr(self, '_filter_timer_running') and self._filter_timer_running:
            self._filter_delay = min(self._filter_delay + 5, self._max_delay)
        
        self._filter_timer_running = True
        self._filter_timer.start(self._filter_delay)
        
    def _execute_delayed_filter(self):
        """Execute the actual filter and reset state"""
        self._filter_timer_running = False
        self._filter_delay = 100  # Reset to initial delay
        self.delayed_filter()

    def delayed_filter(self):
        filter_ = self.image_list.filter_line_edit.parse_filter_text()
        self.proxy_image_list_model.set_filter(filter_)
        self.proxy_image_list_model.filter_changed.emit()
        if filter_ is None:
            all_tags_list_selection_model = (self.all_tags_editor
                                             .all_tags_list.selectionModel())
            all_tags_list_selection_model.clearSelection()
            # Clear the current index.
            self.all_tags_editor.all_tags_list.setCurrentIndex(QModelIndex())
            # Select the previously selected image in the unfiltered image
            # list.
            select_index = settings.value('image_index', type=int) or 0
            self.image_list.list_view.setCurrentIndex(
                self.proxy_image_list_model.index(select_index, 0))
        else:
            # Select the first image.
            self.image_list.list_view.setCurrentIndex(
                self.proxy_image_list_model.index(0, 0))

    @Slot()
    def save_image_index(self, proxy_image_index: QModelIndex):
        """Save the index of the currently selected image."""
        settings_key = ('image_index'
                        if self.proxy_image_list_model.filter is None
                        else 'filtered_image_index')
        settings.setValue(settings_key, proxy_image_index.row())


    @Slot(float)
    def set_rating(self, rating: float, interactive: bool = False,
                   event: QMouseEvent|None = None):
        """Set the rating from 0.0 to 1.0.

        In the future, half-stars '⯪' might be included, but right now it's
        causing display issues."""
        if event is not None and (event.modifiers() & Qt.ControlModifier) == Qt.ControlModifier:
            # don't set the image but instead the filter
            is_shift = (event.modifiers() & Qt.ShiftModifier) == Qt.ShiftModifier
            stars = f'stars:{'>=' if is_shift else '='}{round(rating*5)}'
            self.image_list.filter_line_edit.setText(stars)
            return

        if interactive and rating == 2.0/10.0 and self.rating == rating:
            rating = 0.0
        self.rating = rating
        for i, label in enumerate(self.star_labels):
            label.setEnabled(True)
            label.setText('★' if 2*i+1 < 10.0*rating else '☆')
        if interactive:
            self.image_list_model.add_to_undo_stack(
                action_name='Change rating', should_ask_for_confirmation=False)
            self.image_viewer.rating_change(rating)
            self.proxy_image_list_model.set_filter(self.proxy_image_list_model.filter)


    @Slot()
    def update_image_tags(self):
        image_index = self.image_tags_editor.image_index
        image: Image = self.image_list_model.data(image_index,
                                                  Qt.ItemDataRole.UserRole)
        if image is None:
            return
        old_tags = image.tags
        new_tags = self.image_tag_list_model.stringList()
        if old_tags == new_tags:
            return
        old_tags_count = len(old_tags)
        new_tags_count = len(new_tags)
        if new_tags_count > old_tags_count:
            self.image_list_model.add_to_undo_stack(
                action_name='Add Tag', should_ask_for_confirmation=False)
        elif new_tags_count == old_tags_count:
            if set(new_tags) == set(old_tags):
                self.image_list_model.add_to_undo_stack(
                    action_name='Reorder Tags',
                    should_ask_for_confirmation=False)
            else:
                self.image_list_model.add_to_undo_stack(
                    action_name='Rename Tag',
                    should_ask_for_confirmation=False)
        elif old_tags_count - new_tags_count == 1:
            self.image_list_model.add_to_undo_stack(
                action_name='Delete Tag', should_ask_for_confirmation=False)
        else:
            self.image_list_model.add_to_undo_stack(
                action_name='Delete Tags', should_ask_for_confirmation=False)
        self.image_list_model.update_image_tags(image_index, new_tags)


    @Slot()
    def set_image_list_filter_text(self, selected_tag: str):
        """
        Construct and set the image list filter text from the selected tag in
        the all tags list.
        """
        escaped_selected_tag = (selected_tag.replace('\\', '\\\\')
                                .replace('"', r'\"').replace("'", r"\'"))
        self.image_list.filter_line_edit.setText(
            f'tag:"{escaped_selected_tag}"')

    @Slot(str)
    def add_tag_to_selected_images(self, tag: str):
        selected_image_indices = self.image_list.get_selected_image_indices()
        self.image_list_model.add_tags([tag], selected_image_indices)
        self.image_tags_editor.select_last_tag()


    def restore(self):
        # Restore the window geometry and state.
        if settings.contains('geometry'):
            self.restoreGeometry(settings.value('geometry', type=bytes))
        else:
            self.showMaximized()
        self.restoreState(settings.value('window_state', type=bytes))
        # Get the last index of the last selected image.
        if settings.contains('image_index'):
            image_index = settings.value('image_index', type=int)
        else:
            image_index = 0
        # Load the last loaded directory.
        if settings.contains('directory_path'):
            directory_path = Path(settings.value('directory_path',
                                                      type=str))
            if directory_path.is_dir():
                self.load_directory(directory_path, select_index=image_index)

    def _add_to_recent_directories(self, dir_path: str):
        """Add directory to recent list, maintaining max size."""
        MAX_RECENT = 10
        recent_dirs = settings.value(
            'recent_directories',
            defaultValue=DEFAULT_SETTINGS['recent_directories'],
            type=list
        )
        # Handle None or non-list values
        if not isinstance(recent_dirs, list):
            recent_dirs = []

        # Remove if already exists (move to top)
        if dir_path in recent_dirs:
            recent_dirs.remove(dir_path)

        # Add to beginning
        recent_dirs.insert(0, dir_path)

        # Limit size
        recent_dirs = recent_dirs[:MAX_RECENT]

        # Save and update menu
        settings.setValue('recent_directories', recent_dirs)
        self.menu_manager._update_recent_folders_menu()
