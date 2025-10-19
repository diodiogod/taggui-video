import shutil
from enum import Enum
from functools import reduce
from operator import or_
from pathlib import Path

from PySide6.QtCore import (QFile, QItemSelection, QItemSelectionModel,
                            QItemSelectionRange, QModelIndex, QSize, QUrl, Qt,
                            Signal, Slot, QPersistentModelIndex, QProcess, QTimer, QRect, QEvent)
from PySide6.QtGui import QDesktopServices, QColor, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDockWidget,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QMenu, QMessageBox, QVBoxLayout,
                               QWidget, QStyledItemDelegate, QToolTip, QStyle)
from pyparsing import (CaselessKeyword, CaselessLiteral, Group, OpAssoc,
                       ParseException, QuotedString, Suppress, Word,
                       infix_notation, nums, one_of, printables)

from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image
from utils.settings import settings
from utils.settings_widgets import SettingsComboBox
from utils.utils import get_confirmation_dialog_reply, pluralize
from utils.grid import Grid


def replace_filter_wildcards(filter_: str | list) -> str | list:
    """
    Replace escaped wildcard characters to make them compatible with the
    `fnmatch` module.
    """
    if isinstance(filter_, str):
        filter_ = filter_.replace(r'\*', '[*]').replace(r'\?', '[?]')
        return filter_
    replaced_filter = []
    for element in filter_:
        replaced_element = replace_filter_wildcards(element)
        replaced_filter.append(replaced_element)
    return replaced_filter


class FilterLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText('Filter Images')
        self.setStyleSheet('padding: 8px;')
        self.setClearButtonEnabled(True)
        optionally_quoted_string = (QuotedString(quote_char='"', esc_char='\\')
                                    | QuotedString(quote_char="'",
                                                   esc_char='\\')
                                    | Word(printables, exclude_chars='()'))
        string_filter_keys = ['tag', 'caption', 'marking', 'crops', 'visible',
                              'name', 'path', 'size', 'target']
        string_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + optionally_quoted_string)
                                     for key in string_filter_keys]
        comparison_operator = one_of('= == != < > <= >=')
        number_filter_keys = ['tags', 'chars', 'tokens', 'stars', 'width',
                              'height', 'area']
        number_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + comparison_operator + Word(nums))
                                     for key in number_filter_keys]
        string_filter_expressions = reduce(or_, string_filter_expressions)
        number_filter_expressions = reduce(or_, number_filter_expressions)
        filter_expressions = (string_filter_expressions
                              | number_filter_expressions
                              | optionally_quoted_string)
        self.filter_text_parser = infix_notation(
            filter_expressions,
            # Operator, number of operands, associativity.
            [(CaselessKeyword('NOT'), 1, OpAssoc.RIGHT),
             (CaselessKeyword('AND'), 2, OpAssoc.LEFT),
             (CaselessKeyword('OR'), 2, OpAssoc.LEFT)])

    def parse_filter_text(self) -> list | str | None:
        filter_text = self.text()
        if not filter_text:
            self.setStyleSheet('padding: 8px;')
            return None
        try:
            filter_ = self.filter_text_parser.parse_string(
                filter_text, parse_all=True).as_list()[0]
            filter_ = replace_filter_wildcards(filter_)
            self.setStyleSheet('padding: 8px;')
            return filter_
        except ParseException:
            # Change the background color when the filter text is invalid.
            if self.palette().color(self.backgroundRole()).lightness() < 128:
                # Dark red for dark mode.
                self.setStyleSheet('padding: 8px; background-color: #442222;')
            else:
                # Light red for light mode.
                self.setStyleSheet('padding: 8px; background-color: #ffdddd;')
            return None


class SelectionMode(str, Enum):
    DEFAULT = 'Default'
    TOGGLE = 'Toggle'


class ImageDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = {}

    def clear_labels(self):
        """Clear all stored labels (called on model reset)."""
        self.labels.clear()

    def sizeHint(self, option, index):
        # In IconMode, return compact size (just the thumbnail)
        if isinstance(self.parent(), QListView) and self.parent().viewMode() == QListView.ViewMode.IconMode:
            icon_size = self.parent().iconSize()
            return QSize(icon_size.width() + 10, icon_size.height() + 10)  # Small padding
        # In ListMode, use default size hint with text
        return index.data(Qt.ItemDataRole.SizeHintRole)

    def paint(self, painter, option, index):
        # Validate index and painter before painting
        if not index.isValid():
            return

        # Additional safety: check if model and data are valid
        try:
            if not index.model():
                return
            # Try to access data to ensure index is truly valid
            index.data(Qt.ItemDataRole.DisplayRole)
        except (RuntimeError, AttributeError):
            return

        # Check if we're in IconMode (compact view without text)
        is_icon_mode = isinstance(self.parent(), QListView) and self.parent().viewMode() == QListView.ViewMode.IconMode

        if is_icon_mode:
            # In IconMode: paint only the icon, no text
            try:
                icon = index.data(Qt.ItemDataRole.DecorationRole)
                if icon and not icon.isNull():
                    # Paint background if selected
                    if option.state & QStyle.StateFlag.State_Selected:
                        painter.fillRect(option.rect, option.palette.highlight())

                    # Paint just the icon, centered
                    icon_size = self.parent().iconSize()
                    x = option.rect.x() + (option.rect.width() - icon_size.width()) // 2
                    y = option.rect.y() + (option.rect.height() - icon_size.height()) // 2
                    icon.paint(painter, x, y, icon_size.width(), icon_size.height())
            except RuntimeError:
                return
        else:
            # In ListMode: use default painting with text
            try:
                super().paint(painter, option, index)
            except RuntimeError:
                # Silently ignore paint errors during model reset
                return

            p_index = QPersistentModelIndex(index)
            if p_index.isValid() and p_index in self.labels:
                label_text = self.labels[p_index]
                painter.setBrush(QColor(255, 255, 255, 163))
                painter.drawRect(option.rect)
                painter.drawText(option.rect, label_text, Qt.AlignCenter)

        # Draw N*4+1 stamp for video files (in both modes)
        self._draw_n4_plus_1_stamp(painter, option, index)

    def update_label(self, index: QModelIndex, label: str):
        p_index = QPersistentModelIndex(index)
        self.labels[p_index] = label
        self.parent().update(p_index)

    def remove_label(self, index: QPersistentModelIndex):
        p_index = QPersistentModelIndex(index)
        if p_index in self.labels:
            del self.labels[p_index]
            self.parent().update(index)

    def helpEvent(self, event, view, option, index):
        """Provide tooltip for N*4+1 stamp on hover."""
        if event.type() == QEvent.ToolTip and index.isValid():
            try:
                # Get the image data
                image = index.data(Qt.ItemDataRole.UserRole)
                if not image or not hasattr(image, 'is_video') or not image.is_video:
                    return False

                # Check if video has metadata with frame count
                if not hasattr(image, 'video_metadata') or not image.video_metadata:
                    return False

                frame_count = image.video_metadata.get('frame_count', 0)
                if frame_count <= 0:
                    return False

                # Check N*4+1 rule: (frame_count - 1) % 4 == 0
                is_valid = (frame_count - 1) % 4 == 0

                # Stamp position: top-left corner
                margin = 2
                stamp_rect = QRect(option.rect.left() + margin,
                                  option.rect.top() + margin,
                                  80, 20)

                # Check if mouse is over the stamp
                if stamp_rect.contains(event.pos()):
                    tooltip_text = f"N*4+1 validation: {'Valid' if is_valid else 'Invalid'}\nFrame count: {frame_count}"
                    QToolTip.showText(event.globalPos(), tooltip_text, view, 2000)  # 2 second duration
                    return True
                else:
                    # Hide tooltip if not over stamp
                    QToolTip.hideText()
                    return False
            except Exception:
                pass
        return super().helpEvent(event, view, option, index)

    def _draw_n4_plus_1_stamp(self, painter, option, index):
        """Draw N*4+1 validation stamp on video file previews."""
        try:
            # Get the image data
            image = index.data(Qt.ItemDataRole.UserRole)
            if not image or not hasattr(image, 'is_video') or not image.is_video:
                return

            # Check if video has metadata with frame count
            if not hasattr(image, 'video_metadata') or not image.video_metadata:
                return

            frame_count = image.video_metadata.get('frame_count', 0)
            if frame_count <= 0:
                return

            # Check N*4+1 rule: (frame_count - 1) % 4 == 0
            is_valid = (frame_count - 1) % 4 == 0

            # Set up painter for stamp
            painter.save()

            # Stamp position: top-left corner
            margin = 2
            text_rect = QRect(option.rect.left() + margin,
                              option.rect.top() + margin,
                              80, 20)  # Width and height for text

            # Set font size and bold
            font = painter.font()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)

            # Draw subtle glow (shadow)
            painter.setPen(QPen(QColor(0, 0, 0, 100), 1))  # Semi-transparent black
            glow_text = "✓N*4+1" if is_valid else "✗N*4+1"
            painter.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignLeft | Qt.AlignTop, glow_text)

            # Set text color
            if is_valid:
                painter.setPen(QPen(QColor(76, 175, 80), 2))  # Green
            else:
                painter.setPen(QPen(QColor(244, 67, 54), 2))  # Red

            # Draw text
            text = "✓N*4+1" if is_valid else "✗N*4+1"
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, text)

            painter.restore()

        except Exception:
            # Silently ignore any errors in stamp drawing
            pass


class ImageListView(QListView):
    tags_paste_requested = Signal(list, list)
    directory_reload_requested = Signal()

    def __init__(self, parent, proxy_image_list_model: ProxyImageListModel,
                 tag_separator: str, image_width: int):
        super().__init__(parent)
        self.proxy_image_list_model = proxy_image_list_model
        self.tag_separator = tag_separator
        self.setModel(proxy_image_list_model)
        self.delegate = ImageDelegate(self)
        self.setItemDelegate(self.delegate)

        # Get source model for signal connections
        source_model = proxy_image_list_model.sourceModel()

        # Clear delegate labels when model resets to avoid painting stale indexes
        source_model.modelReset.connect(self.delegate.clear_labels)

        # Disable updates during model reset to prevent paint errors
        # Use source model signals since proxy may not forward modelAboutToBeReset
        source_model.modelAboutToBeReset.connect(self._disable_updates)
        source_model.modelReset.connect(self._enable_updates)

        self.setWordWrap(True)
        self.setDragEnabled(True)

        # Zoom settings
        self.min_thumbnail_size = 64
        self.max_thumbnail_size = 512
        self.column_switch_threshold = 150  # Below this size, switch to multi-column

        # Load saved zoom level or use default
        self.current_thumbnail_size = settings.value('image_list_thumbnail_size', image_width, type=int)
        self.current_thumbnail_size = max(self.min_thumbnail_size,
                                          min(self.max_thumbnail_size, self.current_thumbnail_size))

        # If the actual height of the image is greater than 3 times the width,
        # the image will be scaled down to fit.
        self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

        # Set initial view mode based on size
        self._update_view_mode()

        invert_selection_action = self.addAction('Invert Selection')
        invert_selection_action.setShortcut('Ctrl+I')
        invert_selection_action.triggered.connect(self.invert_selection)
        copy_tags_action = self.addAction('Copy Tags')
        copy_tags_action.setShortcut('Ctrl+C')
        copy_tags_action.triggered.connect(
            self.copy_selected_image_tags)
        paste_tags_action = self.addAction('Paste Tags')
        paste_tags_action.setShortcut('Ctrl+V')
        paste_tags_action.triggered.connect(
            self.paste_tags)
        self.copy_file_names_action = self.addAction('Copy File Name')
        self.copy_file_names_action.setShortcut('Ctrl+Alt+C')
        self.copy_file_names_action.triggered.connect(
            self.copy_selected_image_file_names)
        self.copy_paths_action = self.addAction('Copy Path')
        self.copy_paths_action.setShortcut('Ctrl+Shift+C')
        self.copy_paths_action.triggered.connect(
            self.copy_selected_image_paths)
        self.move_images_action = self.addAction('Move Images to...')
        self.move_images_action.setShortcut('Ctrl+M')
        self.move_images_action.triggered.connect(
            self.move_selected_images)
        self.copy_images_action = self.addAction('Copy Images to...')
        self.copy_images_action.setShortcut('Ctrl+Shift+M')
        self.copy_images_action.triggered.connect(
            self.copy_selected_images)
        self.duplicate_images_action = self.addAction('Duplicate Images')
        self.duplicate_images_action.triggered.connect(
            self.duplicate_selected_images)
        self.delete_images_action = self.addAction('Delete Images')
        # Setting the shortcut to `Del` creates a conflict with tag deletion.
        self.delete_images_action.setShortcut('Ctrl+Del')
        self.delete_images_action.triggered.connect(
            self.delete_selected_images)
        self.open_image_action = self.addAction('Open Image in Default App')
        self.open_image_action.setShortcut('Ctrl+O')
        self.open_image_action.triggered.connect(self.open_image)
        self.open_folder_action = self.addAction('Open on Windows Explorer')
        self.open_folder_action.triggered.connect(self.open_folder)
        self.restore_backup_action = self.addAction('Restore from Backup')
        self.restore_backup_action.triggered.connect(self.restore_backup)

        self.context_menu = QMenu(self)
        self.context_menu.addAction('Select All Images', self.selectAll,
                                    shortcut='Ctrl+A')
        self.context_menu.addAction(invert_selection_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(copy_tags_action)
        self.context_menu.addAction(paste_tags_action)
        self.context_menu.addAction(self.copy_file_names_action)
        self.context_menu.addAction(self.copy_paths_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.move_images_action)
        self.context_menu.addAction(self.copy_images_action)
        self.context_menu.addAction(self.duplicate_images_action)
        self.context_menu.addAction(self.delete_images_action)
        self.context_menu.addAction(self.open_image_action)
        self.context_menu.addAction(self.open_folder_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.restore_backup_action)
        self.selectionModel().selectionChanged.connect(
            self.update_context_menu_actions)

    def contextMenuEvent(self, event):
        self.context_menu.exec_(event.globalPos())

    def wheelEvent(self, event):
        """Handle Ctrl+scroll wheel for zooming thumbnails."""
        if event.modifiers() == Qt.ControlModifier:
            # Get scroll direction
            delta = event.angleDelta().y()

            # Adjust thumbnail size
            zoom_step = 20  # Pixels per scroll step
            if delta > 0:
                # Scroll up = zoom in (larger thumbnails)
                new_size = min(self.current_thumbnail_size + zoom_step, self.max_thumbnail_size)
            else:
                # Scroll down = zoom out (smaller thumbnails)
                new_size = max(self.current_thumbnail_size - zoom_step, self.min_thumbnail_size)

            if new_size != self.current_thumbnail_size:
                self.current_thumbnail_size = new_size
                self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

                # Update view mode (single column vs multi-column)
                self._update_view_mode()

                # Save to settings
                settings.setValue('image_list_thumbnail_size', self.current_thumbnail_size)

            event.accept()
        else:
            # Normal scroll behavior - but boost scroll speed in IconMode
            if self.viewMode() == QListView.ViewMode.IconMode:
                # In icon mode, manually scroll by a reasonable pixel amount
                delta = event.angleDelta().y()
                scroll_amount = delta * 2  # Multiply by 2 for faster scrolling
                current_value = self.verticalScrollBar().value()
                self.verticalScrollBar().setValue(current_value - scroll_amount)
                event.accept()
            else:
                # Default scroll behavior in ListMode
                super().wheelEvent(event)

    def _update_view_mode(self):
        """Switch between single column (ListMode) and multi-column (IconMode) based on thumbnail size."""
        if self.current_thumbnail_size >= self.column_switch_threshold:
            # Large thumbnails: single column list view
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setFlow(QListView.Flow.TopToBottom)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setWrapping(False)
            self.setSpacing(0)
            self.setGridSize(QSize(-1, -1))  # Reset grid size to default
        else:
            # Small thumbnails: compact multi-column grid view (no text labels)
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setWrapping(True)
            self.setSpacing(2)  # Minimal spacing for compact layout
            # Use fixed grid based on icon size for tight packing
            grid_size = self.current_thumbnail_size + 10  # Small padding
            self.setGridSize(QSize(grid_size, grid_size))
            # Force item delegate to recalculate sizes
            self.scheduleDelayedItemsLayout()

    @Slot(Grid)
    def show_crop_size(self, grid):
        index = self.currentIndex()
        if index.isValid():
            image = index.data(Qt.ItemDataRole.UserRole)
            if grid is None:
                self.delegate.remove_label(index)
            else:
                crop_delta = grid.screen.size() - grid.visible.size()
                crop_fit = max(crop_delta.width(), crop_delta.height())
                crop_fit_text = f' (-{crop_fit})' if crop_fit > 0 else ''
                label = f'image: {image.dimensions[0]}x{image.dimensions[1]}\n'\
                        f'crop: {grid.screen.width()}x{grid.screen.height()}{crop_fit_text}\n'\
                        f'target: {grid.target.width()}x{grid.target.height()}'
                if grid.aspect_ratio is not None:
                    label += '✅' if grid.aspect_ratio[2] else ''
                    label += f'  {grid.aspect_ratio[0]}:{grid.aspect_ratio[1]}'
                self.delegate.update_label(index, label)

    def _disable_updates(self):
        """Disable widget updates during model reset."""
        self.setUpdatesEnabled(False)
        self.viewport().setUpdatesEnabled(False)

    def _enable_updates(self):
        """Re-enable widget updates after model reset."""
        # Defer re-enabling updates to next event loop iteration
        # This ensures the view's internal state is fully updated before repainting
        QTimer.singleShot(0, self._do_enable_updates)

    def _do_enable_updates(self):
        """Actually re-enable updates (called after event loop processes)."""
        self.setUpdatesEnabled(True)
        self.viewport().setUpdatesEnabled(True)

    @Slot()
    def invert_selection(self):
        selected_proxy_rows = {index.row() for index in self.selectedIndexes()}
        all_proxy_rows = set(range(self.proxy_image_list_model.rowCount()))
        unselected_proxy_rows = all_proxy_rows - selected_proxy_rows
        first_unselected_proxy_row = min(unselected_proxy_rows, default=0)
        item_selection = QItemSelection()
        for row in unselected_proxy_rows:
            item_selection.append(
                QItemSelectionRange(self.proxy_image_list_model.index(row, 0)))
        self.setCurrentIndex(self.model().index(first_unselected_proxy_row, 0))
        self.selectionModel().select(
            item_selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def get_selected_images(self) -> list[Image]:
        selected_image_proxy_indices = self.selectedIndexes()
        selected_images = [index.data(Qt.ItemDataRole.UserRole)
                           for index in selected_image_proxy_indices]
        return selected_images

    @Slot()
    def copy_selected_image_tags(self):
        selected_images = self.get_selected_images()
        selected_image_captions = [self.tag_separator.join(image.tags)
                                   for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_captions))

    def get_selected_image_indices(self) -> list[QModelIndex]:
        selected_image_proxy_indices = self.selectedIndexes()
        selected_image_indices = [
            self.proxy_image_list_model.mapToSource(proxy_index)
            for proxy_index in selected_image_proxy_indices]
        return selected_image_indices

    @Slot()
    def paste_tags(self):
        selected_image_count = len(self.selectedIndexes())
        if selected_image_count > 1:
            reply = get_confirmation_dialog_reply(
                title='Paste Tags',
                question=f'Paste tags to {selected_image_count} selected '
                         f'images?')
            if reply != QMessageBox.StandardButton.Yes:
                return
        tags = QApplication.clipboard().text().split(self.tag_separator)
        selected_image_indices = self.get_selected_image_indices()
        self.tags_paste_requested.emit(tags, selected_image_indices)

    @Slot()
    def copy_selected_image_file_names(self):
        selected_images = self.get_selected_images()
        selected_image_file_names = [image.path.name
                                     for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_file_names))

    @Slot()
    def copy_selected_image_paths(self):
        selected_images = self.get_selected_images()
        selected_image_paths = [str(image.path) for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_paths))

    @Slot()
    def move_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        caption = (f'Select directory to move {selected_image_count} selected '
                   f'{pluralize("Image", selected_image_count)} and '
                   f'{pluralize("caption", selected_image_count)} to')
        move_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption=caption,
            dir=settings.value('directory_path', type=str))
        if not move_directory_path:
            return
        move_directory_path = Path(move_directory_path)
        for image in selected_images:
            try:
                image.path.replace(move_directory_path / image.path.name)
                caption_file_path = image.path.with_suffix('.txt')
                if caption_file_path.exists():
                    caption_file_path.replace(
                        move_directory_path / caption_file_path.name)
            except OSError:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to move {image.path} to '
                                     f'{move_directory_path}.')
        self.directory_reload_requested.emit()

    @Slot()
    def copy_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        caption = (f'Select directory to copy {selected_image_count} selected '
                   f'{pluralize("Image", selected_image_count)} and '
                   f'{pluralize("caption", selected_image_count)} to')
        copy_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption=caption,
            dir=settings.value('directory_path', type=str))
        if not copy_directory_path:
            return
        copy_directory_path = Path(copy_directory_path)
        for image in selected_images:
            try:
                shutil.copy(image.path, copy_directory_path)
                caption_file_path = image.path.with_suffix('.txt')
                if caption_file_path.exists():
                    shutil.copy(caption_file_path, copy_directory_path)
            except OSError:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to copy {image.path} to '
                                     f'{copy_directory_path}.')

    @Slot()
    def duplicate_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        if selected_image_count == 0:
            return

        # Get the source model to add duplicated images
        source_model = self.proxy_image_list_model.sourceModel()

        duplicated_count = 0
        for image in selected_images:
            try:
                # Generate unique name for duplicate
                original_path = image.path
                directory = original_path.parent
                stem = original_path.stem
                suffix = original_path.suffix

                # Find a unique name by appending "_copy" or "_copy2", etc.
                counter = 1
                new_stem = f"{stem}_copy"
                new_path = directory / f"{new_stem}{suffix}"
                while new_path.exists():
                    counter += 1
                    new_stem = f"{stem}_copy{counter}"
                    new_path = directory / f"{new_stem}{suffix}"

                # Copy the media file
                shutil.copy2(original_path, new_path)

                # Copy caption file if it exists
                caption_file_path = original_path.with_suffix('.txt')
                if caption_file_path.exists():
                    new_caption_path = new_path.with_suffix('.txt')
                    shutil.copy2(caption_file_path, new_caption_path)

                # Copy JSON metadata file if it exists
                json_file_path = original_path.with_suffix('.json')
                if json_file_path.exists():
                    new_json_path = new_path.with_suffix('.json')
                    shutil.copy2(json_file_path, new_json_path)

                # Add the new image to the model
                source_model.add_image(new_path)

                duplicated_count += 1

            except OSError as e:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to duplicate {image.path}: {str(e)}')

        if duplicated_count > 0:
            # Emit signal to reload directory (this will refresh the list)
            self.directory_reload_requested.emit()

    @Slot()
    def delete_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        title = f'Delete {pluralize("Image", selected_image_count)}'
        question = (f'Delete {selected_image_count} selected '
                    f'{pluralize("image", selected_image_count)} and '
                    f'{"its" if selected_image_count == 1 else "their"} '
                    f'{pluralize("caption", selected_image_count)}?')
        reply = get_confirmation_dialog_reply(title, question)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Check if any selected videos are currently loaded and unload them
        # Hierarchy: ImageListView -> container -> ImageList (QDockWidget) -> MainWindow
        main_window = self.parent().parent().parent()  # Get main window reference
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                # Check if we're deleting the currently loaded video
                for image in selected_images:
                    if image.path == currently_loaded_path:
                        # Unload the video first (stop playback and release resources)
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails for all selected videos to release graphics resources
        for image in selected_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        # If we cleaned up a video, give Qt/Windows a moment to release file handles
        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)  # 100ms delay
            QApplication.processEvents()  # Process pending events to ensure cleanup completes

        # Force garbage collection to release any remaining file handles
        import gc
        gc.collect()

        from PySide6.QtCore import QThread
        import time

        for image in selected_images:
            success = False

            # For videos, try multiple times with delays (Windows file handle release is async)
            max_retries = 3 if (hasattr(image, 'is_video') and image.is_video) else 1

            for attempt in range(max_retries):
                if attempt > 0:
                    # Wait and retry
                    QThread.msleep(150)  # Wait 150ms between retries
                    QApplication.processEvents()
                    gc.collect()

                # Try Qt's moveToTrash first
                image_file = QFile(str(image.path))
                if image_file.moveToTrash():
                    success = True
                    break
                elif attempt == max_retries - 1:
                    # Last attempt - ask user for permanent deletion
                    reply = QMessageBox.question(
                        self, 'Trash Failed',
                        f'Could not move {image.path.name} to trash.\nDelete permanently?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No  # Default to No for safety
                    )
                    if reply == QMessageBox.Yes:
                        if image_file.remove():
                            success = True

            if not success:
                QMessageBox.critical(self, 'Error', f'Failed to delete {image.path}.')
                continue

            # Also try to delete caption file
            caption_file_path = image.path.with_suffix('.txt')
            if caption_file_path.exists():
                caption_file = QFile(caption_file_path)
                if not caption_file.moveToTrash():
                    # For caption files, try permanent deletion without asking again
                    caption_file.remove()  # Silent operation for captions
        self.directory_reload_requested.emit()

    @Slot()
    def open_image(self):
        selected_images = self.get_selected_images()
        image_path = selected_images[0].path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(image_path)))

    @Slot()
    def open_folder(self):
        selected_images = self.get_selected_images()
        if selected_images:
            folder_path = selected_images[0].path.parent
            file_path = selected_images[0].path
            # Use explorer.exe with /select flag to highlight the file
            QProcess.startDetached('explorer.exe', ['/select,', str(file_path)])

    @Slot()
    def restore_backup(self):
        """Restore selected images/videos from their .backup files."""
        from PySide6.QtWidgets import QMessageBox
        import shutil

        selected_images = self.get_selected_images()
        if not selected_images:
            return

        # Find which images have backups
        images_with_backups = []
        for img in selected_images:
            backup_path = Path(str(img.path) + '.backup')
            if backup_path.exists():
                images_with_backups.append((img, backup_path))

        if not images_with_backups:
            QMessageBox.information(None, "No Backups", "No backup files found for selected images.")
            return

        # Confirm restoration
        count = len(images_with_backups)
        reply = QMessageBox.question(
            None,
            "Restore from Backup",
            f"Restore {count} {'file' if count == 1 else 'files'} from backup?\n\n"
            f"This will replace the current {'file' if count == 1 else 'files'} with the backup version.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Restore files
        restored = 0
        for img, backup_path in images_with_backups:
            try:
                shutil.copy2(str(backup_path), str(img.path))
                restored += 1
            except Exception as e:
                QMessageBox.warning(None, "Restore Error", f"Failed to restore {img.path.name}:\n{str(e)}")

        if restored > 0:
            QMessageBox.information(None, "Restore Complete", f"Successfully restored {restored} {'file' if restored == 1 else 'files'}.")
            # Trigger reload to update thumbnails
            self.directory_reload_requested.emit()

    @Slot()
    def update_context_menu_actions(self):
        selected_image_count = len(self.selectedIndexes())
        copy_file_names_action_name = (
            f'Copy File {pluralize("Name", selected_image_count)}')
        copy_paths_action_name = (f'Copy '
                                  f'{pluralize("Path", selected_image_count)}')
        move_images_action_name = (
            f'Move {pluralize("Image", selected_image_count)} to...')
        copy_images_action_name = (
            f'Copy {pluralize("Image", selected_image_count)} to...')
        duplicate_images_action_name = (
            f'Duplicate {pluralize("Image", selected_image_count)}')
        delete_images_action_name = (
            f'Delete {pluralize("Image", selected_image_count)}')
        self.copy_file_names_action.setText(copy_file_names_action_name)
        self.copy_paths_action.setText(copy_paths_action_name)
        self.move_images_action.setText(move_images_action_name)
        self.copy_images_action.setText(copy_images_action_name)
        self.duplicate_images_action.setText(duplicate_images_action_name)
        self.delete_images_action.setText(delete_images_action_name)
        self.open_image_action.setVisible(selected_image_count == 1)
        self.open_folder_action.setVisible(selected_image_count >= 1)

        # Check if any selected images have backups
        has_backup = False
        if selected_image_count > 0:
            selected_images = self.get_selected_images()
            has_backup = any((Path(str(img.path) + '.backup')).exists() for img in selected_images)
        restore_action_name = f'Restore {pluralize("Backup", selected_image_count)}'
        self.restore_backup_action.setText(restore_action_name)
        self.restore_backup_action.setVisible(has_backup)


class ImageList(QDockWidget):
    def __init__(self, proxy_image_list_model: ProxyImageListModel,
                 tag_separator: str, image_width: int):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_list')
        self.setWindowTitle('Images')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        self.filter_line_edit = FilterLineEdit()

        # Selection mode and Sort on same row
        selection_sort_layout = QHBoxLayout()
        selection_mode_label = QLabel('Selection')
        self.selection_mode_combo_box = SettingsComboBox(
            key='image_list_selection_mode')
        self.selection_mode_combo_box.addItems(list(SelectionMode))

        sort_label = QLabel('Sort')
        self.sort_combo_box = SettingsComboBox(key='image_list_sort_by')
        self.sort_combo_box.addItems(['Name', 'Modified', 'Created',
                                       'Size', 'Type', 'Random'])

        selection_sort_layout.addWidget(selection_mode_label)
        selection_sort_layout.addWidget(self.selection_mode_combo_box, stretch=1)
        selection_sort_layout.addWidget(sort_label)
        selection_sort_layout.addWidget(self.sort_combo_box, stretch=1)

        self.list_view = ImageListView(self, proxy_image_list_model,
                                       tag_separator, image_width)
        self.image_index_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(selection_sort_layout)
        layout.addWidget(self.list_view)
        layout.addWidget(self.image_index_label)
        self.setWidget(container)

        self.selection_mode_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.selection_mode_combo_box.currentText())

        # Connect sort signal
        self.sort_combo_box.currentTextChanged.connect(self._on_sort_changed)

    def set_selection_mode(self, selection_mode: str):
        if selection_mode == SelectionMode.DEFAULT:
            self.list_view.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
        elif selection_mode == SelectionMode.TOGGLE:
            self.list_view.setSelectionMode(
                QAbstractItemView.SelectionMode.MultiSelection)

    @Slot()
    def update_image_index_label(self, proxy_image_index: QModelIndex):
        image_count = self.proxy_image_list_model.rowCount()
        unfiltered_image_count = (self.proxy_image_list_model.sourceModel()
                                  .rowCount())
        label_text = f'Image {proxy_image_index.row() + 1} / {image_count}'
        if image_count != unfiltered_image_count:
            label_text += f' ({unfiltered_image_count} total)'
        self.image_index_label.setText(label_text)

    @Slot()
    def go_to_previous_image(self):
        if self.list_view.selectionModel().currentIndex().row() == 0:
            return
        self.list_view.clearSelection()
        previous_image_index = self.proxy_image_list_model.index(
            self.list_view.selectionModel().currentIndex().row() - 1, 0)
        self.list_view.setCurrentIndex(previous_image_index)

    @Slot()
    def go_to_next_image(self):
        if (self.list_view.selectionModel().currentIndex().row()
                == self.proxy_image_list_model.rowCount() - 1):
            return
        self.list_view.clearSelection()
        next_image_index = self.proxy_image_list_model.index(
            self.list_view.selectionModel().currentIndex().row() + 1, 0)
        self.list_view.setCurrentIndex(next_image_index)

    @Slot()
    def jump_to_first_untagged_image(self):
        """
        Select the first image that has no tags, or the last image if all
        images are tagged.
        """
        proxy_image_index = None
        for proxy_image_index in range(self.proxy_image_list_model.rowCount()):
            image: Image = self.proxy_image_list_model.data(
                self.proxy_image_list_model.index(proxy_image_index, 0),
                Qt.ItemDataRole.UserRole)
            if not image.tags:
                break
        if proxy_image_index is None:
            return
        self.list_view.clearSelection()
        self.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(proxy_image_index, 0))

    def get_selected_image_indices(self) -> list[QModelIndex]:
        return self.list_view.get_selected_image_indices()

    @Slot(str)
    def _on_sort_changed(self, sort_by: str):
        """Sort images when sort option changes."""
        # Get the source model
        source_model = self.proxy_image_list_model.sourceModel()
        if not source_model or not hasattr(source_model, 'images'):
            return

        # Natural sort key function for filenames (handles numbers correctly)
        def natural_sort_key(text):
            import re
            return [int(c) if c.isdigit() else c.lower()
                    for c in re.split(r'(\d+)', text)]

        # Safe file stat getter with fallback
        def safe_stat(img, attr, default=0):
            try:
                return getattr(img.path.stat(), attr)
            except (OSError, AttributeError):
                return default

        # Sort the images list
        try:
            # Emit layoutAboutToBeChanged before sorting
            source_model.layoutAboutToBeChanged.emit()

            if sort_by == 'Name':
                source_model.images.sort(key=lambda img: natural_sort_key(img.path.name))
            elif sort_by == 'Modified':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_mtime'), reverse=True)
            elif sort_by == 'Created':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_ctime'), reverse=True)
            elif sort_by == 'Size':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_size'), reverse=True)
            elif sort_by == 'Type':
                source_model.images.sort(key=lambda img: (img.path.suffix.lower(), natural_sort_key(img.path.name)))
            elif sort_by == 'Random':
                import random
                random.shuffle(source_model.images)

            # Emit layoutChanged after sorting
            source_model.layoutChanged.emit()
        except Exception as e:
            import traceback
            print(f"Sort error: {e}")
            traceback.print_exc()
            # Ensure layoutChanged is emitted even on error
            source_model.layoutChanged.emit()

