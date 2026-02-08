from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewFileOpsMixin:
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

        # Calculate the index to focus after deletion
        # Get all selected indices and find the maximum (last in sort order)
        selected_indices = sorted([idx.row() for idx in self.selectedIndexes()])
        if selected_indices:
            max_selected_row = selected_indices[-1]
            total_rows = self.proxy_image_list_model.rowCount()
            # Set next index: use the row after the last deleted one, or the one before if it's the last
            next_index = max_selected_row + 1 - len(selected_indices)
            if next_index >= total_rows - len(selected_indices):
                # If we're deleting at the end, focus on the image before the first deleted one
                next_index = max(0, selected_indices[0] - 1)
            # Store in main window for use after reload
            main_window = self.parent().parent().parent()
            main_window.post_deletion_index = next_index

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

        # Remove deleted images from DB index so they don't reappear on reload
        try:
            _src_model = self.proxy_image_list_model.sourceModel()
            if hasattr(_src_model, '_db') and _src_model._db:
                from utils.settings import settings as _settings
                directory_path = Path(_settings.value('directory_path', type=str))
                rel_paths = []
                for image in selected_images:
                    try:
                        rel_paths.append(str(image.path.relative_to(directory_path)))
                    except ValueError:
                        rel_paths.append(image.path.name)
                _src_model._db.remove_images_by_paths(rel_paths)
        except Exception as e:
            print(f"[DELETE] Warning: failed to clean DB index: {e}")

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
            has_backup = any((Path(str(img.path) + '.backup')).exists() for img in selected_images if img is not None)
        restore_action_name = f'Restore {pluralize("Backup", selected_image_count)}'
        self.restore_backup_action.setText(restore_action_name)
        self.restore_backup_action.setVisible(has_backup)


    def _show_page_indicator(self):
        """Show page indicator overlay when scrolling in pagination mode."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return

        total_items = source_model._total_count if hasattr(source_model, '_total_count') else source_model.rowCount()
        if total_items <= 0:
            return

        current_page = getattr(self, '_current_page', 0)
        strategy = self._get_masonry_strategy(source_model)
        if getattr(self, '_stick_to_edge', None) == "top":
            current_page = 0
        elif getattr(self, '_stick_to_edge', None) == "bottom":
            current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE)
        elif (
            getattr(self, '_drag_release_anchor_active', False)
            and self._drag_release_anchor_idx is not None
            and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
        ):
            current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, self._drag_release_anchor_idx // source_model.PAGE_SIZE))
        # Track whether anchor already resolved the page (don't override).
        _anchor_resolved = (
            getattr(self, '_drag_release_anchor_active', False)
            and self._drag_release_anchor_idx is not None
            and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
        )
        if self.use_masonry and strategy == "windowed_strict":
            # Strict mode: derive page from actual visible masonry items so
            # the indicator matches what the user sees (not the formula-based
            # estimate which drifts when real item heights != masonry_avg_h).
            if not _anchor_resolved:
                scroll_offset = self.verticalScrollBar().value()
                viewport_rect = self.viewport().rect().translated(0, scroll_offset)
                vis_items = self._get_masonry_visible_items(viewport_rect)
                real_vis = [it for it in vis_items if it.get('index', -1) >= 0]
                if real_vis:
                    mid_idx = real_vis[len(real_vis) // 2]['index']
                    current_page = max(0, min(
                        (total_items - 1) // source_model.PAGE_SIZE,
                        mid_idx // source_model.PAGE_SIZE))
                else:
                    current_page = self._strict_page_from_position(
                        scroll_offset, source_model)
        elif self.use_masonry:
            # Non-strict masonry: prefer viewport-visible items for page indicator.
            scroll_offset = self.verticalScrollBar().value()
            viewport_rect = self.viewport().rect().translated(0, scroll_offset)
            visible_items = self._get_masonry_visible_items(viewport_rect)
            real_items = [it for it in visible_items if it.get('index', -1) >= 0]
            if real_items and getattr(self, '_stick_to_edge', None) is None and not _anchor_resolved:
                mid_idx = real_items[len(real_items) // 2]['index']
                current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, mid_idx // source_model.PAGE_SIZE))
        else:
            # Non-masonry mode: selection-based indicator is intuitive.
            if not _anchor_resolved:
                current_idx = self.currentIndex()
                if current_idx.isValid():
                    try:
                        global_idx = current_idx.row()
                        if hasattr(self.model(), 'mapToSource'):
                            src_idx = self.model().mapToSource(current_idx)
                            if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                                mapped = source_model.get_global_index_for_row(src_idx.row())
                                if mapped >= 0:
                                    global_idx = mapped
                        current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, global_idx // source_model.PAGE_SIZE))
                    except Exception:
                        pass

        # Use _total_count for buffered mode (rowCount only returns loaded items)
        total_pages = (total_items + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE
        total_pages = max(1, total_pages)

        # During scrollbar drag, represent current target page from slider position.
        # Selection often remains on an old item and is misleading in this mode.
        if self._scrollbar_dragging or self._drag_preview_mode:
            if self._drag_target_page is not None:
                current_page = max(0, min(total_pages - 1, int(self._drag_target_page)))
            else:
                source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
                slider_pos = int(self.verticalScrollBar().sliderPosition())
                if self._use_local_anchor_masonry(source_model):
                    current_page = self._strict_page_from_position(slider_pos, source_model)
                else:
                    scroll_max = max(1, int(getattr(self, '_drag_scroll_max_baseline', self.verticalScrollBar().maximum())))
                    fraction = max(0.0, min(1.0, slider_pos / scroll_max))
                    current_page = int(round(fraction * (total_pages - 1)))
                    current_page = max(0, min(total_pages - 1, current_page))

        # Create label if needed
        if not self._page_indicator_label:
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            self._page_indicator_label = QLabel(self.viewport())
            self._page_indicator_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 180);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
            """)
            self._page_indicator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Update text and position
        self._page_indicator_label.setText(f"Page {current_page + 1} / {total_pages}")
        self._page_indicator_label.adjustSize()

        # Position at top-right corner
        viewport_rect = self.viewport().rect()
        label_x = viewport_rect.width() - self._page_indicator_label.width() - 20
        label_y = 20
        self._page_indicator_label.move(label_x, label_y)

        # Show and reset fade timer
        self._page_indicator_label.setWindowOpacity(1.0)
        self._page_indicator_label.show()
        self._page_indicator_timer.stop()
        self._page_indicator_timer.start(1500)  # Fade after 1.5s


    def _fade_out_page_indicator(self):
        """Fade out page indicator after delay."""
        if not self._page_indicator_label:
            return

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        # Animate opacity from 1.0 to 0.0
        self._page_fade_animation = QPropertyAnimation(self._page_indicator_label, b"windowOpacity")
        self._page_fade_animation.setDuration(500)  # 500ms fade
        self._page_fade_animation.setStartValue(1.0)
        self._page_fade_animation.setEndValue(0.0)
        self._page_fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._page_fade_animation.finished.connect(self._page_indicator_label.hide)
        self._page_fade_animation.start()

    # DISABLED: Cache warming causes UI blocking
    # def _start_cache_warming(self):
    #     """Start background cache warming after idle period."""
    #     source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
    #     if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
    #         return
    #
    #     # Don't start cache warming while enrichment is running (causes UI blocking)
    #     # Check if any images still need enrichment (have placeholder dimensions)
    #     if hasattr(source_model, 'images') and source_model.images:
    #         needs_enrichment = any(img.dimensions == (512, 512) for img in source_model.images[:100])  # Sample first 100
    #         if needs_enrichment:
    #             print("[CACHE WARM] Skipping - enrichment still in progress")
    #             # Retry in 5 seconds
    #             self._cache_warm_idle_timer.start(5000)
    #             return
    #
    #     # Default to 'down' if never scrolled
    #     if not hasattr(self, '_scroll_direction') or self._scroll_direction is None:
    #         self._scroll_direction = 'down'
    #         print(f"[CACHE WARM] Starting without prior scroll, defaulting to 'down'")
    #
    #     # Get visible items to determine where to start warming
    #     viewport_rect = self.viewport().rect()
    #     visible_items = self._get_masonry_visible_items(viewport_rect)
    #     if not visible_items:
    #         return
    #
    #     # Calculate start index based on scroll direction
    #     if self._scroll_direction == 'down':
    #         # Warm cache ahead (below visible area)
    #         start_idx = max(item['index'] for item in visible_items) + 1
    #     else:
    #         # Warm cache above visible area
    #         start_idx = min(item['index'] for item in visible_items) - 500
    #         start_idx = max(0, start_idx)
    #
    #     # Start cache warming in the model
    #     if hasattr(source_model, 'start_cache_warming'):
    #         source_model.start_cache_warming(start_idx, self._scroll_direction)

    # DISABLED: Cache warming causes UI blocking
    # def _stop_cache_warming(self):
    #     """Stop background cache warming immediately."""
    #     source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
    #     if source_model and hasattr(source_model, 'stop_cache_warming'):
    #         source_model.stop_cache_warming()


    def _flush_cache_saves(self):
        """Flush pending cache saves after truly idle (2+ seconds)."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, 'set_scrolling_state'):
            # Tell model scrolling stopped and flush pending saves
            source_model.set_scrolling_state(False)

    # Cache status removed - now shown in main window status bar
