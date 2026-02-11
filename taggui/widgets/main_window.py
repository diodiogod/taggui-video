import time
import hashlib
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QKeyCombination, QModelIndex, QUrl, Qt, QTimer, Slot
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QDesktopServices,
                           QIcon, QKeySequence, QShortcut, QMouseEvent)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QMainWindow,
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
        self.post_deletion_index = None  # Track index to focus after deletion
        self._load_session_id = 0  # Increments per load; used to ignore stale callbacks.
        self._restore_in_progress = False
        self._restore_target_global_rank = -1
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
        self._update_main_window_title()

        # Create toolbar and menus
        self.toolbar_manager.create_toolbar()
        self.rating = self.toolbar_manager.rating
        self.star_labels = self.toolbar_manager.star_labels

        self.image_list = ImageList(self.proxy_image_list_model,
                                    tag_separator, image_list_image_width)
        self.image_list.sort_combo_box.currentTextChanged.connect(
            self._on_folder_sort_pref_changed)
        self.image_list.media_type_combo_box.currentTextChanged.connect(
            self._on_folder_media_pref_changed)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self.image_list)

        # Detect dock widget resize (splitter movement)
        self.image_list.list_view.installEventFilter(self)
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

        # TEMP: Disable status bar to test if it fixes gray space
        # status_bar = self.statusBar()
        # status_bar.setSizeGripEnabled(False)
        # self.image_list_model.cache_warm_progress.connect(self._update_cache_status)
        # QTimer.singleShot(1000, lambda: self._update_cache_status(0, 0))

        # Connect video playback signals to freeze list view during playback
        self.image_viewer.video_player.playback_started.connect(self._freeze_list_view)
        self.image_viewer.video_player.playback_paused.connect(self._unfreeze_list_view)

        # Unfreeze list view temporarily during user interaction
        # Re-freezes automatically after 200ms of idle if video is playing
        self.image_list.list_view.verticalScrollBar().valueChanged.connect(
            self._unfreeze_for_interaction)
        self.image_list_selection_model.currentChanged.connect(
            self._unfreeze_for_interaction)

        # Unfreeze on layout changes
        self.proxy_image_list_model.layoutChanged.connect(
            self._unfreeze_for_interaction)
        self.proxy_image_list_model.modelReset.connect(
            self._unfreeze_for_interaction)
        self.proxy_image_list_model.filter_changed.connect(
            self._unfreeze_for_interaction)

        # Unfreeze on sort change
        self.image_list.sort_combo_box.currentTextChanged.connect(
            self._unfreeze_for_interaction)
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
        self._filter_timer.timeout.connect(self._execute_delayed_filter)
        self._filter_delay = 250  # 250ms - balanced between responsive and smooth
        self._max_delay = 500
        self._filter_timer_running = False

        # List view freeze/unfreeze management for video playback performance
        self._list_view_frozen = False
        self._video_is_playing = False
        self._unfreeze_timer = QTimer()
        self._unfreeze_timer.setSingleShot(True)
        self._unfreeze_timer.timeout.connect(self._refreeze_after_interaction)
        settings.change.connect(self._on_setting_changed)

    def _freeze_list_view(self):
        """Called when video playback starts."""
        self._video_is_playing = True
        # Delay freeze slightly to allow initial frame to render
        QTimer.singleShot(100, self._apply_freeze_if_idle)

    def _apply_freeze_if_idle(self):
        """Actually freeze the list view if no interaction is happening."""
        if self._video_is_playing and not self._unfreeze_timer.isActive():
            if not self._list_view_frozen:
                self.image_list.list_view.setUpdatesEnabled(False)
                self._list_view_frozen = True
                # print("[VIDEO] List view frozen for playback")

    def _unfreeze_list_view(self):
        """Called when video is paused/stopped."""
        self._video_is_playing = False
        # Don't unfreeze automatically - let user interaction handle it
        # Static list doesn't need repaints whether video is playing or not

    def _unfreeze_for_interaction(self):
        """Temporarily unfreeze during user interaction, then re-freeze after idle."""
        # Safety check - might be called before initialization completes
        if not hasattr(self, '_list_view_frozen'):
            return

        # Unfreeze if currently frozen
        if self._list_view_frozen:
            self.image_list.list_view.setUpdatesEnabled(True)
            self._list_view_frozen = False
            # print("[VIDEO] List view unfrozen (user interaction)")

        # Restart timer - will re-freeze after 200ms of no interaction
        self._unfreeze_timer.stop()
        self._unfreeze_timer.start(200)

    def _refreeze_after_interaction(self):
        """Re-freeze list view after interaction has stopped."""
        # Only re-freeze if video is playing (otherwise keep unfrozen for responsiveness)
        if self._video_is_playing and not self._list_view_frozen:
            self.image_list.list_view.setUpdatesEnabled(False)
            self._list_view_frozen = True
            # print("[VIDEO] List view re-frozen (interaction ended)")
        elif not self._video_is_playing and self._list_view_frozen:
            # Video stopped while frozen - unfreeze for normal use
            self.image_list.list_view.setUpdatesEnabled(True)
            self._list_view_frozen = False
            # print("[VIDEO] List view unfrozen (no video playing)")

    def eventFilter(self, obj, event):
        """Filter events for list view to detect splitter resize."""
        if obj == self.image_list.list_view and event.type() == event.Type.Resize:
            self._unfreeze_for_interaction()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """Handle window resize - unfreeze list to allow layout update."""
        super().resizeEvent(event)
        self._unfreeze_for_interaction()

    def closeEvent(self, event: QCloseEvent):
        """Save the window geometry and state before closing."""
        print("[SHUTDOWN] closeEvent triggered")
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('window_state', self.saveState())
        # Save marker size setting
        if hasattr(self, 'toolbar_manager'):
            settings.setValue('fixed_marker_size', self.toolbar_manager.fixed_marker_size_spinbox.value())

        # Manually save current selection to ensure it persists
        if hasattr(self, 'image_list') and hasattr(self.image_list, 'list_view'):
             idx = self.image_list.list_view.currentIndex()
             if idx.isValid():
                 # Use the slot directly to save
                 self.save_image_index(idx)

        # Flush any pending DB updates before closing
        if hasattr(self, 'image_list_model'):
            self.image_list_model._flush_db_cache_flags()
            
        settings.sync()
        print("[SHUTDOWN] Settings synced")

        super().closeEvent(event)

    def set_font_size(self):
        font = self.app.font()
        font_size = settings.value(
            'font_size', defaultValue=DEFAULT_SETTINGS['font_size'], type=int)
        font.setPointSize(font_size)
        self.app.setFont(font)

    @Slot(str, object)
    def _on_setting_changed(self, key: str, _value):
        """Apply selected settings live without requiring restart."""
        if key == 'masonry_list_switch_threshold':
            list_view = getattr(getattr(self, 'image_list', None), 'list_view', None)
            if list_view is None:
                return
            try:
                threshold = int(_value)
            except (TypeError, ValueError):
                threshold = DEFAULT_SETTINGS['masonry_list_switch_threshold']
            threshold = max(list_view.min_thumbnail_size, min(1024, threshold))
            list_view.column_switch_threshold = threshold
            list_view._update_view_mode()
            print(f"[MASONRY] Live list auto-switch threshold: {threshold}px")
            return

        if key not in ('max_pages_in_memory', 'thumbnail_eviction_pages'):
            return

        raw_max, eviction_pages, effective_max = self.image_list_model._resolve_page_memory_limits()
        self.image_list_model.MAX_PAGES_IN_MEMORY = effective_max
        if getattr(self.image_list_model, '_paginated_mode', False):
            self.image_list_model._evict_old_pages()
        if effective_max != raw_max:
            print(
                f"[PAGINATION] Live max pages in memory: {effective_max} "
                f"(raised from {raw_max} for eviction window {eviction_pages})"
            )
        else:
            print(f"[PAGINATION] Live max pages in memory: {effective_max}")

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

    def _update_main_window_title(self, selected_file_name: str | None = None):
        """Show folder and selected file name in the main window title."""
        base_title = "TagGUI"
        folder_name = self.directory_path.name if self.directory_path else None
        if folder_name:
            base_title = f"{base_title} - {folder_name}"
        if selected_file_name:
            self.setWindowTitle(f"{base_title} - {selected_file_name}")
        else:
            self.setWindowTitle(base_title)

    def _folder_view_settings_prefix(self, path: Path | None = None) -> str:
        """Stable per-folder key prefix for UI view preferences."""
        folder_path = (path or self.directory_path)
        if folder_path is None:
            return ""
        try:
            normalized = str(folder_path.resolve()).replace("\\", "/").lower()
        except Exception:
            normalized = str(folder_path).replace("\\", "/").lower()
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]
        return f"folder_view_prefs/{digest}"

    def _get_folder_view_preferences(self, path: Path) -> tuple[str, str]:
        """Load folder-specific sort/media preferences."""
        prefix = self._folder_view_settings_prefix(path)
        if not prefix:
            return "", ""
        sort_value = str(settings.value(f"{prefix}/sort", "", type=str) or "").strip()
        media_value = str(settings.value(f"{prefix}/media_type", "", type=str) or "").strip()
        if media_value not in {"All", "Images", "Videos"}:
            media_value = ""
        return sort_value, media_value

    def _save_folder_view_preferences(self, *,
                                      sort_value: str | None = None,
                                      media_value: str | None = None):
        """Persist sort/media choices for the currently loaded folder."""
        if self.directory_path is None:
            return
        prefix = self._folder_view_settings_prefix(self.directory_path)
        if not prefix:
            return
        sort_text = str(sort_value if sort_value is not None else self.image_list.sort_combo_box.currentText())
        media_text = str(media_value if media_value is not None else self.image_list.media_type_combo_box.currentText())
        settings.setValue(f"{prefix}/sort", sort_text)
        settings.setValue(f"{prefix}/media_type", media_text)
        settings.setValue(f"{prefix}/path", str(self.directory_path))

    def _save_folder_last_selected_path(self, image_path: Path):
        """Persist last selected image path for current folder."""
        if self.directory_path is None:
            return
        prefix = self._folder_view_settings_prefix(self.directory_path)
        if not prefix:
            return
        settings.setValue(f"{prefix}/last_selected_path", str(image_path))

    def _get_folder_last_selected_path(self, path: Path) -> str | None:
        """Load folder-specific last selected image path if present."""
        prefix = self._folder_view_settings_prefix(path)
        if not prefix:
            return None
        value = str(settings.value(f"{prefix}/last_selected_path", "", type=str) or "").strip()
        return value or None

    def _apply_folder_view_preferences(self, path: Path):
        """Apply folder-specific sort/media values to combo boxes."""
        sort_pref, media_pref = self._get_folder_view_preferences(path)
        sort_combo = self.image_list.sort_combo_box
        media_combo = self.image_list.media_type_combo_box

        if sort_pref:
            valid_sorts = {sort_combo.itemText(i) for i in range(sort_combo.count())}
            if sort_pref in valid_sorts and sort_combo.currentText() != sort_pref:
                prev = sort_combo.blockSignals(True)
                try:
                    sort_combo.setCurrentText(sort_pref)
                finally:
                    sort_combo.blockSignals(prev)

        if media_pref:
            if media_pref in {"All", "Images", "Videos"} and media_combo.currentText() != media_pref:
                prev = media_combo.blockSignals(True)
                try:
                    media_combo.setCurrentText(media_pref)
                finally:
                    media_combo.blockSignals(prev)

    @Slot(str)
    def _on_folder_sort_pref_changed(self, sort_text: str):
        self._save_folder_view_preferences(sort_value=sort_text)

    @Slot(str)
    def _on_folder_media_pref_changed(self, media_text: str):
        self._save_folder_view_preferences(media_value=media_text)

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
                       save_path_to_settings: bool = False,
                       select_path: str | None = None):
        self._load_session_id += 1
        load_session_id = self._load_session_id
        self.directory_path = path.resolve()
        if save_path_to_settings:
            settings.setValue('directory_path', str(self.directory_path))
            self._add_to_recent_directories(str(self.directory_path))
        self._update_main_window_title()
        self.image_list_model.load_directory(path)
        self.image_list.filter_line_edit.clear()
        # self.all_tags_editor.filter_line_edit.clear() # Keeping this

        # Restore folder-specific sort/media preferences, if present.
        self._apply_folder_view_preferences(self.directory_path)

        # Restore folder-specific last selected image when caller did not
        # explicitly request a selection.
        if not select_path:
            folder_saved_path = self._get_folder_last_selected_path(self.directory_path)
            if folder_saved_path:
                select_path = folder_saved_path

        # Track unfiltered total right after load to detect media-filter empty states.
        source_total_before_media_filter = (
            int(getattr(self.image_list_model, '_total_count', 0) or 0)
            if getattr(self.image_list_model, '_paginated_mode', False)
            else int(self.image_list_model.rowCount())
        )

        # Apply persisted media type filter (All/Images/Videos) for this folder.
        # Must call delayed_filter() directly — clear() above won't fire
        # textChanged if the field was already empty (e.g. on startup).
        media_type = self.image_list.media_type_combo_box.currentText()
        self.proxy_image_list_model.set_media_type_filter(media_type)
        self.delayed_filter()
        # Folder-load fallback only: if persisted media filter empties results
        # on a non-empty folder, reset to All to avoid "looks stuck" confusion.
        if (media_type != 'All'
                and source_total_before_media_filter > 0
                and self.proxy_image_list_model.rowCount() == 0):
            print(f"[MEDIA] Persisted filter '{media_type}' returned 0 items on folder load; resetting to 'All'")
            self.image_list.media_type_combo_box.setCurrentText('All')

        # Apply saved sort order after loading
        saved_sort = self.image_list.sort_combo_box.currentText()
        if saved_sort:
            self.image_list._on_sort_changed(saved_sort, preserve_selection=False)
        self._save_folder_view_preferences()
            
        # Try to restore selection by path (more robust)
        self._restore_global_rank = -1
        if select_path:
            src_row = self.image_list_model.get_index_for_path(Path(select_path))
            if src_row != -1:
                # Store global rank for scroll restore (local rows shift as pages load)
                self._restore_global_rank = self.image_list_model.get_global_index_for_row(src_row)
                # Map source row to proxy index (considering filter/sort)
                src_idx = self.image_list_model.index(src_row, 0)
                proxy_idx = self.proxy_image_list_model.mapFromSource(src_idx)
                if proxy_idx.isValid():
                    select_index = proxy_idx.row()
                    print(f"[RESTORE] Restored selection from path: {select_path} (Row {select_index})")

        # Clear the current index first to make sure that the `currentChanged`
        # signal is emitted even if the image at the index is already selected.
        self.image_list_selection_model.clearSelection()
        self.image_list_selection_model.clearCurrentIndex()
        selected_index = self.proxy_image_list_model.index(select_index, 0)
        view = self.image_list.list_view
        source_model = self.image_list_model
        _restore_global_rank = getattr(self, '_restore_global_rank', -1)
        view._selected_global_index = _restore_global_rank if _restore_global_rank >= 0 else None
        view._resize_anchor_page = None
        view._resize_anchor_until = 0.0

        def _fresh_view_index(index: QModelIndex) -> QModelIndex:
            """Re-resolve row against current model to avoid stale QModelIndex crashes."""
            model = view.model()
            if model is None or not index.isValid():
                return QModelIndex()
            if index.model() is not model:
                return QModelIndex()
            row = index.row()
            if row < 0 or row >= model.rowCount():
                return QModelIndex()
            return model.index(row, 0)

        def _set_current_and_select(index: QModelIndex) -> QModelIndex:
            """Keep current index and selected row synchronized."""
            fresh = _fresh_view_index(index)
            if not fresh.isValid():
                sel_model = view.selectionModel()
                if sel_model is not None:
                    sel_model.clearSelection()
                    sel_model.clearCurrentIndex()
                return QModelIndex()
            sel_model = view.selectionModel()
            if sel_model is not None:
                sel_model.setCurrentIndex(
                    fresh,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
            else:
                view.setCurrentIndex(fresh)
            return fresh

        is_paginated_strict = (
            getattr(source_model, '_paginated_mode', False)
            and hasattr(view, '_use_local_anchor_masonry')
            and view._use_local_anchor_masonry(source_model)
        )
        if is_paginated_strict and _restore_global_rank >= 0:
            page_size = getattr(source_model, 'PAGE_SIZE', 1000)
            view._restore_target_page = _restore_global_rank // page_size
            view._restore_target_global_index = _restore_global_rank
            view._restore_anchor_until = time.time() + 12.0
            self._restore_in_progress = True
            self._restore_target_global_rank = int(_restore_global_rank)
        else:
            view._restore_target_page = None
            view._restore_target_global_index = None
            view._restore_anchor_until = 0.0
            self._restore_in_progress = False
            self._restore_target_global_rank = -1

        if is_paginated_strict and _restore_global_rank >= 0:
            # Avoid provisional row-based selection during startup restore.
            # Row mappings can drift as pages are inserted, causing a brief
            # wrong image flash before global-rank restore settles.
            try:
                self.image_viewer.view.clear_scene()
            except Exception:
                pass
        else:
            _set_current_and_select(selected_index)
        self.centralWidget().setCurrentWidget(self.image_viewer)

        # Scroll to selected image after layout is ready.
        # In windowed_strict paginated mode, the masonry window may not include
        # the selected item's page. We move the scrollbar to the correct page
        # so masonry recalcs for the right area, then scrollTo centers the item.
        # IMPORTANT: Never call setCurrentIndex here — that would change the
        # selection as page loads shift row numbers, breaking the image viewer.
        scroll_done = [False]

        def do_scroll():
            if scroll_done[0]:
                return
            if load_session_id != self._load_session_id:
                try:
                    self.image_list.list_view.layout_ready.disconnect(do_scroll)
                except Exception:
                    pass
                return
            scroll_done[0] = True
            try:
                self.image_list.list_view.layout_ready.disconnect(do_scroll)
            except Exception:
                pass

            if is_paginated_strict and _restore_global_rank >= 0:
                page_size = getattr(source_model, 'PAGE_SIZE', 1000)
                target_page = _restore_global_rank // page_size
                canonical_max = view._strict_canonical_domain_max(source_model)
                total_count = getattr(source_model, '_total_count', 0) or 0
                max_page = max(1, (total_count + page_size - 1) // page_size) - 1
                if max_page > 0 and canonical_max > 0:
                    # Set restore target page directly on view — bypasses all
                    # scrollbar-to-page derivation (which drifts through
                    # competing writers in completion/updateGeometries/_check_and_load_pages).
                    view._restore_target_page = target_page

                    target_scroll = int(target_page / max_page * canonical_max)
                    sb = view.verticalScrollBar()
                    sb.setMaximum(canonical_max)
                    sb.setValue(target_scroll)
                    print(f"[RESTORE] Scrollbar moved to page {target_page} "
                          f"(rank {_restore_global_rank})")

                    # After masonry recalcs for the target page, find the item
                    # in masonry_items by global index and center the viewport.
                    final_done = [False]
                    final_attempts = [0]

                    def do_final_scroll():
                        if final_done[0]:
                            return
                        if load_session_id != self._load_session_id:
                            final_done[0] = True
                            try:
                                view.layout_ready.disconnect(do_final_scroll)
                            except Exception:
                                pass
                            return
                        # User clicked — restore is superseded.
                        if not getattr(self, '_restore_in_progress', False):
                            final_done[0] = True
                            try:
                                view.layout_ready.disconnect(do_final_scroll)
                            except Exception:
                                pass
                            return
                        final_attempts[0] += 1

                        # Rebind current selection by GLOBAL rank (not stale local row).
                        # During restore, newly loaded pages can be inserted before the
                        # selected page, so the original local row may drift to another image.
                        target_idx = _restore_global_rank
                        rebound_proxy_index = QModelIndex()
                        if hasattr(source_model, 'get_loaded_row_for_global_index'):
                            loaded_row = source_model.get_loaded_row_for_global_index(target_idx)
                            if loaded_row >= 0:
                                src_idx = source_model.index(loaded_row, 0)
                                proxy_model = view.model()
                                rebound_proxy_index = (
                                    proxy_model.mapFromSource(src_idx)
                                    if hasattr(proxy_model, 'mapFromSource')
                                    else src_idx
                                )
                                rebound_proxy_index = _fresh_view_index(rebound_proxy_index)
                                if (rebound_proxy_index.isValid()
                                        and view.currentIndex() != rebound_proxy_index):
                                    _set_current_and_select(rebound_proxy_index)

                        # Find item position directly in masonry items.
                        for item in (view._masonry_items or []):
                            if item.get('index') == target_idx:
                                final_done[0] = True
                                try:
                                    view.layout_ready.disconnect(do_final_scroll)
                                except Exception:
                                    pass
                                # Center viewport on this item
                                item_center_y = item['y'] + item['height'] // 2
                                viewport_h = view.viewport().height()
                                scroll_to = max(0, item_center_y - viewport_h // 2)
                                view.verticalScrollBar().setValue(scroll_to)
                                # Ensure current index/viewer are synchronized with target.
                                if not rebound_proxy_index.isValid() and hasattr(source_model, 'get_loaded_row_for_global_index'):
                                    loaded_row = source_model.get_loaded_row_for_global_index(target_idx)
                                    if loaded_row >= 0:
                                        src_idx = source_model.index(loaded_row, 0)
                                        proxy_model = view.model()
                                        rebound_proxy_index = (
                                            proxy_model.mapFromSource(src_idx)
                                            if hasattr(proxy_model, 'mapFromSource')
                                            else src_idx
                                        )
                                        rebound_proxy_index = _fresh_view_index(rebound_proxy_index)
                                if rebound_proxy_index.isValid():
                                    _set_current_and_select(rebound_proxy_index)
                                    self._restore_in_progress = False
                                    self._restore_target_global_rank = -1
                                print(f"[RESTORE] Centered on global index "
                                      f"{target_idx} at y={item['y']}")
                                return

                        # Retry briefly while target page/window is still materializing.
                        if final_attempts[0] < 20:
                            QTimer.singleShot(150, do_final_scroll)
                            return

                        # Fallback: keep whichever index is known-correct.
                        final_done[0] = True
                        try:
                            view.layout_ready.disconnect(do_final_scroll)
                        except Exception:
                            pass
                        fallback_index = (
                            rebound_proxy_index
                            if rebound_proxy_index.isValid()
                            else selected_index
                        )
                        fallback_index = _fresh_view_index(fallback_index)
                        if fallback_index.isValid():
                            _set_current_and_select(fallback_index)
                            view.scrollTo(
                                fallback_index,
                                QAbstractItemView.ScrollHint.PositionAtCenter,
                            )
                        self._restore_in_progress = False
                        self._restore_target_global_rank = -1

                    view.layout_ready.connect(do_final_scroll)
                    # Keep restore override alive through startup page-load/recalc bursts.
                    # It is also cleared immediately on user-driven scrolling.
                    def _clear_restore():
                        view._restore_target_page = None
                        view._restore_target_global_index = None
                        view._restore_anchor_until = 0.0
                        self._restore_in_progress = False
                        self._restore_target_global_rank = -1
                    QTimer.singleShot(12000, _clear_restore)
                    QTimer.singleShot(2000, do_final_scroll)
                    return

            # Non-paginated or no restore info: simple scrollTo
            selected_index_fresh = _fresh_view_index(selected_index)
            if selected_index_fresh.isValid():
                view.scrollTo(
                    selected_index_fresh, QAbstractItemView.ScrollHint.PositionAtCenter)

        self.image_list.list_view.layout_ready.connect(do_scroll)

        # Fallback timeout in case layout_ready doesn't fire (e.g., grid layout)
        QTimer.singleShot(2000, do_scroll)

        # Set focus to image list so arrow keys work immediately
        self.image_list.list_view.setFocus()

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

        # If we have a post-deletion index, use that instead of the saved index
        if self.post_deletion_index is not None:
            select_index = self.post_deletion_index
            self.post_deletion_index = None  # Clear it after use
        else:
            select_index = settings.value(select_index_key, type=int) or 0

        self.load_directory(self.directory_path)
        load_session_id = self._load_session_id
        self.image_list.filter_line_edit.setText(filter_text)
        # If the selected image index is out of bounds due to images being
        # deleted, select the last image.
        if select_index >= self.proxy_image_list_model.rowCount():
            select_index = self.proxy_image_list_model.rowCount() - 1
        target_index = self.proxy_image_list_model.index(select_index, 0)
        if target_index.isValid():
            self.image_list.list_view.setCurrentIndex(target_index)

        # Scroll to selected image after layout is ready (same pattern as load_directory)
        scroll_done = [False]

        def do_scroll():
            if scroll_done[0]:
                return
            if load_session_id != self._load_session_id:
                try:
                    self.image_list.list_view.layout_ready.disconnect(do_scroll)
                except Exception:
                    pass
                return
            scroll_done[0] = True
            current_model = self.image_list.list_view.model()
            fresh_target_index = QModelIndex()
            if (current_model is not None
                    and target_index.isValid()
                    and target_index.model() is current_model):
                row = target_index.row()
                if 0 <= row < current_model.rowCount():
                    fresh_target_index = current_model.index(row, 0)
            if fresh_target_index.isValid():
                self.image_list.list_view.scrollTo(
                    fresh_target_index, QAbstractItemView.ScrollHint.PositionAtCenter)
            try:
                self.image_list.list_view.layout_ready.disconnect(do_scroll)
            except:
                pass

        self.image_list.list_view.layout_ready.connect(do_scroll)
        # Fallback timeout in case layout_ready doesn't fire
        QTimer.singleShot(2000, do_scroll)

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
        import time
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        current_text = self.image_list.filter_line_edit.text()
        print(f"[{timestamp}] 🔤 KEYSTROKE: filter_text='{current_text}'")

        # Notify image list of rapid input for adaptive masonry delay
        self.image_list.list_view.on_filter_keystroke()

        # CRITICAL: Stop any filter timer on new keystroke
        if self._filter_timer.isActive():
            self._filter_timer.stop()
            print(f"[{timestamp}]   -> CANCELLED filter timer")

        # CRITICAL: Cancel any pending masonry recalculation on new keystroke
        if self.image_list.list_view._masonry_recalc_timer.isActive():
            self.image_list.list_view._masonry_recalc_timer.stop()
            print(f"[{timestamp}]   -> CANCELLED pending masonry timer")

        if hasattr(self, '_filter_timer_running') and self._filter_timer_running:
            self._filter_delay = min(self._filter_delay + 5, self._max_delay)

        self._filter_timer_running = True
        self._filter_timer.start(self._filter_delay)

        # Visual feedback - subtle opacity change (works with any theme)
        # self.image_list.filter_line_edit.setStyleSheet(
        #     "QLineEdit { opacity: 0.7; }"
        # )
        
    def _execute_delayed_filter(self):
        """Execute the actual filter and reset state"""
        self._filter_timer_running = False
        self._filter_delay = 250  # Reset to initial delay

        # Reset visual feedback
        self.image_list.filter_line_edit.setStyleSheet("")

        self.delayed_filter()

    def delayed_filter(self):
        media_type = self.image_list.media_type_combo_box.currentText()
        self.proxy_image_list_model.set_media_type_filter(media_type)
        filter_ = self.image_list.filter_line_edit.parse_filter_text()
        self.proxy_image_list_model.set_filter(filter_)
        # filter_changed.emit() is already called by set_filter() - don't emit twice!
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
        """Save the index and path of the currently selected image."""
        if self._should_suppress_transient_restore_index(proxy_image_index):
            return
        if self._should_suppress_transient_drag_selection(proxy_image_index):
            return
        # Post-click freeze: ignore recalc-driven selection mutations.
        import time as _t
        view = self.image_list.list_view
        if _t.time() < float(getattr(view, '_user_click_selection_frozen_until', 0.0) or 0.0):
            return
        settings_key = ('image_index'
                        if self.proxy_image_list_model.filter is None
                        else 'filtered_image_index')
        settings.setValue(settings_key, proxy_image_index.row())

        if not proxy_image_index.isValid():
            self._update_main_window_title()
            return

        # Save path for robust restoration (independent of filter/sort)
        if proxy_image_index.isValid():
            source_index = self.proxy_image_list_model.mapToSource(
                proxy_image_index)
            if source_index.isValid():
                try:
                    # Access helper method for path (works for Normal & Paginated)
                    img = self.image_list_model.get_image_at_row(source_index.row())
                    if img:
                        self._save_folder_last_selected_path(img.path)
                        settings.setValue('last_selected_path', str(img.path))
                        print(f"[SAVE] Selected path: {img.path.name}")
                        self._update_main_window_title(img.path.name)
                    else:
                        self._update_main_window_title()
                except (IndexError, AttributeError):
                    self._update_main_window_title()
            else:
                self._update_main_window_title()

    def _should_suppress_transient_restore_index(self, proxy_image_index: QModelIndex) -> bool:
        """Ignore intermediate selection/current changes while startup restore is settling."""
        if not getattr(self, '_restore_in_progress', False):
            return False
        target = int(getattr(self, '_restore_target_global_rank', -1) or -1)
        if target < 0:
            return False
        if not proxy_image_index.isValid():
            return True
        try:
            src_index = self.proxy_image_list_model.mapToSource(proxy_image_index)
            if not src_index.isValid():
                return True
            mapped = self.image_list_model.get_global_index_for_row(src_index.row())
            if isinstance(mapped, int) and mapped >= 0:
                return mapped != target
            return True
        except Exception:
            return True

    def _proxy_index_to_global_rank(self, proxy_image_index: QModelIndex) -> int:
        """Map proxy index to stable global rank; returns -1 on failure."""
        if not proxy_image_index.isValid():
            return -1
        try:
            src_index = self.proxy_image_list_model.mapToSource(proxy_image_index)
            if not src_index.isValid():
                return -1
            mapped = self.image_list_model.get_global_index_for_row(src_index.row())
            return int(mapped) if isinstance(mapped, int) and mapped >= 0 else -1
        except Exception:
            return -1

    def _should_suppress_transient_drag_selection(self, proxy_image_index: QModelIndex) -> bool:
        """Ignore selection churn caused by buffered page remaps during/after drag jumps."""
        view = self.image_list.list_view
        source_model = self.image_list_model
        if not (
            view.use_masonry
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        ):
            return False

        now = time.time()
        lock_until = float(getattr(view, '_selected_global_lock_until', 0.0) or 0.0)
        selected_global = (
            getattr(view, '_selected_global_lock_value', None)
            if now < lock_until else
            getattr(view, '_selected_global_index', None)
        )
        if not (isinstance(selected_global, int) and selected_global >= 0):
            return False

        # Live drag/preview: never treat current-index remaps as user selection changes.
        if getattr(view, '_scrollbar_dragging', False) or getattr(view, '_drag_preview_mode', False):
            return True

        release_active = now < float(getattr(view, '_drag_release_anchor_until', 0.0) or 0.0)
        loading_pages = bool(getattr(source_model, '_loading_pages', set()))
        if not (release_active or loading_pages):
            return False

        mapped = self._proxy_index_to_global_rank(proxy_image_index)
        if mapped < 0:
            return True

        # During drag-release stabilization, only accept current changes that still
        # point to the stable selected global.
        return int(mapped) != int(selected_global)


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
                # Prefer folder-specific selection; fallback to legacy global key.
                select_path = self._get_folder_last_selected_path(directory_path)
                if not select_path and settings.contains('last_selected_path'):
                    select_path = settings.value('last_selected_path', type=str)
                self.load_directory(directory_path, select_index=image_index, select_path=select_path)

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

    def _update_cache_status(self, progress: int, total: int):
        """Update status bar with cache warming progress."""
        # Create persistent label if needed (right-aligned in status bar)
        if not hasattr(self, '_cache_status_label'):
            from PySide6.QtWidgets import QLabel
            self._cache_status_label = QLabel()
            self.statusBar().addPermanentWidget(self._cache_status_label)

        if total == 0:
            # No warming active, show real cache stats
            cached, total_images = self.image_list_model.get_cache_stats()
            if total_images > 0:
                percent = int((cached / total_images) * 100)
                self._cache_status_label.setText(f"💾 Cache: {cached:,} / {total_images:,} ({percent}%)")
            else:
                self._cache_status_label.setText("")
        else:
            # Warming active, show progress
            percent = int((progress / total) * 100) if total > 0 else 0
            self._cache_status_label.setText(f"🔥 Building cache: {progress:,} / {total:,} ({percent}%)")
