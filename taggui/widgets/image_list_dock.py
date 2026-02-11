from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_view import ImageListView

class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ImageList(QDockWidget):
    deletion_marking_changed = Signal()
    directory_reload_requested = Signal()

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
        self.sort_combo_box.addItems(['Default', 'Name', 'Modified', 'Created',
                                       'Size', 'Type', 'Random'])

        self.media_type_combo_box = SettingsComboBox(key='media_type_filter')
        self.media_type_combo_box.addItems(['All', 'Images', 'Videos'])
        self.media_type_combo_box.setMinimumWidth(70)

        selection_sort_layout.addWidget(selection_mode_label)
        selection_sort_layout.addWidget(self.selection_mode_combo_box, stretch=1)
        selection_sort_layout.addWidget(sort_label)
        selection_sort_layout.addWidget(self.sort_combo_box, stretch=1)
        selection_sort_layout.addWidget(self.media_type_combo_box)

        self.list_view = ImageListView(self, proxy_image_list_model,
                                       tag_separator, image_width)

        # Status bar with image index (left) and cache status (right) on same line
        self.image_index_label = ClickableLabel()
        self.cache_status_label = QLabel()
        self.image_index_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_index_label.setToolTip("Click to jump to image index")
        self.image_index_label.clicked.connect(self._on_image_index_label_clicked)
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(5, 2, 5, 2)
        status_layout.addWidget(self.image_index_label)
        status_layout.addStretch()  # Push cache label to the right
        status_layout.addWidget(self.cache_status_label)

        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        layout.setSpacing(0)  # Remove spacing between widgets
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(selection_sort_layout)
        layout.addWidget(self.list_view)
        layout.addLayout(status_layout)
        self.setWidget(container)

        self.selection_mode_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.selection_mode_combo_box.currentText())

        # Connect sort signal
        self.sort_combo_box.currentTextChanged.connect(self._on_sort_changed)

        # DISABLED: Cache warming causes UI blocking
        # Connect cache warming signal to update cache status label
        # source_model = proxy_image_list_model.sourceModel()
        # if hasattr(source_model, 'cache_warm_progress'):
        #     source_model.cache_warm_progress.connect(self._update_cache_status)
        #     # Trigger initial update
        #     QTimer.singleShot(1000, lambda: self._update_cache_status(0, 0))

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
        source_model = self.proxy_image_list_model.sourceModel()

        # In buffered pagination mode, use _total_count instead of rowCount
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            unfiltered_image_count = source_model._total_count if hasattr(source_model, '_total_count') else source_model.rowCount()
        else:
            unfiltered_image_count = source_model.rowCount()

        current_pos = proxy_image_index.row() + 1
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            try:
                src_index = self.proxy_image_list_model.mapToSource(proxy_image_index)
                if src_index.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                    global_idx = source_model.get_global_index_for_row(src_index.row())
                    if global_idx >= 0:
                        current_pos = global_idx + 1
            except Exception:
                pass

        # In buffered mode, denominator should reflect total filtered dataset size, not loaded rowCount.
        denom = image_count
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            denom = unfiltered_image_count

        label_text = f'Image {current_pos} / {denom}'
        if image_count != unfiltered_image_count:
            label_text += f' ({unfiltered_image_count} total)'
        self.image_index_label.setText(label_text)

    @Slot()
    def _on_image_index_label_clicked(self):
        """Open quick jump dialog for image index."""
        self.list_view.show_go_to_image_index_dialog()

    # DISABLED: Cache warming causes UI blocking
    # def _update_cache_status(self, progress: int, total: int):
    #     """Update cache status label (right side of status bar)."""
    #     source_model = self.proxy_image_list_model.sourceModel()
    #     if total == 0:
    #         # No warming active, show real cache stats
    #         if hasattr(source_model, 'get_cache_stats'):
    #             cached, total_images = source_model.get_cache_stats()
    #             if total_images > 0:
    #                 percent = int((cached / total_images) * 100)
    #                 self.cache_status_label.setText(f"💾 Cache: {cached:,} / {total_images:,} ({percent}%)")
    #             else:
    #                 self.cache_status_label.setText("")
    #         else:
    #             self.cache_status_label.setText("")
    #     else:
    #         # Warming active, show progress
    #         percent = int((progress / total) * 100) if total > 0 else 0
    #         self.cache_status_label.setText(f"🔥 Building cache: {progress:,} / {total:,} ({percent}%)")

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
    def _on_sort_changed(self, sort_by: str, preserve_selection: bool = True):
        """Sort images when sort option changes."""
        # Get the source model
        source_model = self.proxy_image_list_model.sourceModel()
        if not source_model or not hasattr(source_model, 'images'):
            return

        # Cancel any ongoing background enrichment (indices will be invalid after sort)
        if hasattr(source_model, '_enrichment_cancelled'):
            source_model._enrichment_cancelled.set()
            print("[SORT] Cancelled background enrichment (reordering images)")

        # Safe file stat getter with fallback
        def safe_stat(img, attr, default=0):
            try:
                return getattr(img.path.stat(), attr)
            except (OSError, AttributeError):
                return default

        # Sort the images list
        try:
            selected_image = None
            if preserve_selection:
                # Get currently selected image BEFORE sorting (to scroll to it after).
                # During folder-load replay, currentIndex can be stale while models churn.
                current_index = self.list_view.currentIndex()
                if (current_index.isValid()
                        and current_index.model() is self.proxy_image_list_model):
                    source_index = self.proxy_image_list_model.mapToSource(current_index)
                    if source_index.isValid():
                        selected_image = source_model.data(
                            source_index, Qt.ItemDataRole.UserRole
                        )
                if selected_image:
                    print(f"[SORT] Will scroll to selected image: {selected_image.path.name}")
                else:
                    print(f"[SORT] No valid current index to scroll to")
            else:
                print("[SORT] Skipping selection capture during folder-load sort replay")

            # BUFFERED PAGINATION MODE: Update DB sort params and reload pages
            if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # Map UI sort option to DB field
                sort_map = {
                    'Default': ('file_name', 'ASC'),
                    'Name': ('file_name', 'ASC'),
                    'Modified': ('mtime', 'DESC'),
                    'Created': ('ctime', 'DESC'),
                    'Size': ('file_size', 'DESC'),
                    'Type': ('file_type', 'ASC'),
                    'Random': ('RANDOM()', 'ASC')  # Now supported in DB
                }

                db_sort_field, db_sort_dir = sort_map.get(sort_by, ('file_name', 'ASC'))
                source_model._sort_field = db_sort_field
                source_model._sort_dir = db_sort_dir
                
                # STABLE RANDOM: Generate a new seed if sorting by Random, to shuffle view
                if sort_by == 'Random':
                    import time
                    source_model._random_seed = int(time.time() * 1000) % 1000000
                
                print(f"[SORT] Buffered mode: changed DB sort to {db_sort_field} {db_sort_dir} (Seed: {getattr(source_model, '_random_seed', 0)})")

                # CRITICAL: Inform Qt that the entire model is being reset
                source_model.beginResetModel()
                
                try:
                    # Clear all pages and reload from DB with new sort
                    with source_model._page_load_lock:
                        source_model._pages.clear()
                        source_model._loading_pages.clear()
                        source_model._page_load_order.clear()

                    # Reload first 3 pages with new sort order
                    for page_num in range(3):
                        source_model._load_page_sync(page_num)
                finally:
                    source_model.endResetModel()

                # Trigger layout update - emit pages_updated FIRST so proxy invalidates
                source_model._emit_pages_updated()
                # source_model.layoutChanged.emit() # Redundant with endResetModel()
                
                # Restart background enrichment (essential for updating placeholders)
                if hasattr(source_model, '_start_paginated_enrichment'):
                    source_model._start_paginated_enrichment()

            else:
                # NORMAL MODE: Sort in-memory list
                source_model.beginResetModel()
                try:
                    if sort_by == 'Default':
                        # Use natural sort from image_list_model (same as initial load)
                        source_model.images.sort(key=lambda img: natural_sort_key(img.path))
                    elif sort_by == 'Name':
                        # Natural sort by filename only (not full path)
                        source_model.images.sort(key=lambda img: natural_sort_key(Path(img.path.name)))
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

                    # Rebuild aspect ratio cache after reordering
                    if hasattr(source_model, '_rebuild_aspect_ratio_cache'):
                        source_model._rebuild_aspect_ratio_cache()
                finally:
                    source_model.endResetModel()

                # Restart background enrichment with new sorted order
                if hasattr(source_model, '_restart_enrichment'):
                    source_model._restart_enrichment()

            # --- SELECTION RESTORATION ---
            # Use a class-level variable and a single shot timer to avoid multiple connections
            if selected_image:
                self._image_to_scroll_to = selected_image
                
                try:
                    # Disconnect previous if any
                    self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
                except Exception:
                    pass
                    
                self.list_view.layout_ready.connect(self._do_scroll_after_sort)
                
                # Fallback timer (1s)
                QTimer.singleShot(1000, self._do_scroll_after_sort)
            else:
                 self.list_view.verticalScrollBar().setValue(0)

        except Exception as e:
            import traceback
            print(f"Sort error: {e}")
            traceback.print_exc()

    @Slot()
    def _do_scroll_after_sort(self):
        """Scroll to the previously selected image after a sort operation completes."""
        if not hasattr(self, '_image_to_scroll_to') or not self._image_to_scroll_to:
            return
            
        selected_image = self._image_to_scroll_to
        self._image_to_scroll_to = None  # Clear to prevent multiple triggers
        
        try:
            # Disconnect to prevent re-triggering from future layouts
            try:
                self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
            except Exception:
                pass
                
            source_model = self.proxy_image_list_model.sourceModel()
            new_proxy_index = QModelIndex()
            
            if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # OPTIMIZATION: In paginated mode, don't iterate all data
                # Just check the first few rows (usually where it ends up after Name sort if it was near top)
                # For 1600 items, we can iterate, but let's be careful.
                row_count = source_model.rowCount()
                for row in range(min(row_count, 3000)): # Cap at 3k for safety
                    image = source_model.data(source_model.index(row, 0), Qt.ItemDataRole.UserRole)
                    if image and image.path == selected_image.path:
                        new_proxy_index = self.proxy_image_list_model.mapFromSource(source_model.index(row, 0))
                        break
            else:
                try:
                    new_source_row = source_model.images.index(selected_image)
                    new_proxy_index = self.proxy_image_list_model.mapFromSource(source_model.index(new_source_row, 0))
                except (ValueError, AttributeError):
                    pass

            if new_proxy_index.isValid():
                from PySide6.QtWidgets import QAbstractItemView
                self.list_view.setCurrentIndex(new_proxy_index)
                self.list_view.scrollTo(new_proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
            else:
                # Not loaded or filtered out
                pass
        except Exception as e:
            print(f"[SORT] Scroll restoration failed: {e}")
            pass

    @Slot()
    def toggle_deletion_marking(self):
        """Toggle the deletion marking for selected images."""
        selected_indices = self.list_view.selectedIndexes()
        print(f"[DEBUG] toggle_deletion_marking called, selected_indices: {len(selected_indices)}")
        if not selected_indices:
            return

        # Get the images and toggle their marking
        for proxy_index in selected_indices:
            source_index = self.proxy_image_list_model.mapToSource(proxy_index)
            image = self.proxy_image_list_model.sourceModel().data(
                source_index, Qt.ItemDataRole.UserRole)
            if image:
                old_value = image.marked_for_deletion
                image.marked_for_deletion = not image.marked_for_deletion
                print(f"[DEBUG] Toggled image {image.path.name}: {old_value} -> {image.marked_for_deletion}")

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        print(f"[DEBUG] Emitting deletion_marking_changed signal")
        self.deletion_marking_changed.emit()

    def get_marked_for_deletion_count(self):
        """Get count of images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        count = 0
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                count += 1
        return count

    @Slot()
    def unmark_all_images(self):
        """Remove deletion marking from all images."""
        source_model = self.proxy_image_list_model.sourceModel()
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion'):
                image.marked_for_deletion = False

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        self.deletion_marking_changed.emit()

    @Slot()
    def delete_marked_images(self):
        """Delete all images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        marked_images = []
        marked_indices = []

        # Collect all marked images and their proxy indices
        for row in range(self.proxy_image_list_model.rowCount()):
            proxy_index = self.proxy_image_list_model.index(row, 0)
            image = self.proxy_image_list_model.data(proxy_index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                marked_images.append(image)
                marked_indices.append(row)

        if not marked_images:
            return

        marked_count = len(marked_images)
        title = f'Delete {pluralize("Image", marked_count)}'
        question = (f'Delete {marked_count} marked '
                    f'{pluralize("image", marked_count)} and '
                    f'{"its" if marked_count == 1 else "their"} '
                    f'{pluralize("caption", marked_count)}?')
        reply = get_confirmation_dialog_reply(title, question)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Calculate the index to focus after deletion
        if marked_indices:
            max_marked_row = marked_indices[-1]
            total_rows = self.proxy_image_list_model.rowCount()
            # Set next index: use the row after the last deleted one, or the one before if it's the last
            next_index = max_marked_row + 1 - len(marked_indices)
            if next_index >= total_rows - len(marked_indices):
                # If we're deleting at the end, focus on the image before the first deleted one
                next_index = max(0, marked_indices[0] - 1)
            # Store in main window for use after reload
            main_window = self.parent()
            main_window.post_deletion_index = next_index

        # Similar cleanup logic as delete_selected_images
        main_window = self.parent()
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                for image in marked_images:
                    if image.path == currently_loaded_path:
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails
        for image in marked_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)
            QApplication.processEvents()

        # Delete files with retries
        import gc
        max_retries = 3
        for image in marked_images:
            success = False
            for attempt in range(max_retries):
                if attempt > 0:
                    QThread.msleep(150)
                    QApplication.processEvents()
                    gc.collect()

                image_file = QFile(str(image.path))
                if image_file.moveToTrash():
                    success = True
                    break
                elif attempt == max_retries - 1:
                    reply = QMessageBox.question(
                        self, 'Trash Failed',
                        f'Could not move {image.path.name} to trash.\nDelete permanently?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        if image_file.remove():
                            success = True

            if not success:
                QMessageBox.critical(self, 'Error', f'Failed to delete {image.path}.')
                continue

            # Delete caption file
            caption_file_path = image.path.with_suffix('.txt')
            if caption_file_path.exists():
                caption_file = QFile(caption_file_path)
                if not caption_file.moveToTrash():
                    caption_file.remove()

        # Remove deleted images from DB index so they don't reappear on reload
        # (load_directory uses DB cache for datasets with 1000+ images).
        try:
            if hasattr(source_model, '_db') and source_model._db:
                from utils.settings import settings as _settings
                directory_path = Path(_settings.value('directory_path', type=str))
                rel_paths = []
                for image in marked_images:
                    try:
                        rel_paths.append(str(image.path.relative_to(directory_path)))
                    except ValueError:
                        rel_paths.append(image.path.name)
                source_model._db.remove_images_by_paths(rel_paths)
        except Exception as e:
            print(f"[DELETE] Warning: failed to clean DB index: {e}")

        self.directory_reload_requested.emit()

__all__ = ["ImageList"]
