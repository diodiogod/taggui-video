"""Manager for connecting signals in main window."""

from PySide6.QtCore import Qt, Slot, QModelIndex
from widgets.image_viewer import ImageMarking

class SignalManager:
    """Manages signal connections for main window."""

    def __init__(self, main_window):
        """Initialize signal manager."""
        self.main_window = main_window

    def connect_all_signals(self):
        """Connect all signals for main window components."""
        self.connect_toolbar_signals()
        self.connect_image_list_signals()
        self.connect_image_tags_editor_signals()
        self.connect_all_tags_editor_signals()
        self.connect_auto_captioner_signals()
        self.connect_auto_markings_signals()
        self.connect_video_controls_signals()

    def connect_toolbar_signals(self):
        """Connect toolbar-related signals."""
        toolbar_manager = self.main_window.toolbar_manager
        image_viewer = self.main_window.image_viewer

        for toolbar in toolbar_manager.get_toolbars():
            toolbar.visibilityChanged.connect(
                lambda _visible, tm=toolbar_manager: self.main_window.menu_manager.toggle_toolbar_action.setChecked(
                    tm.any_toolbar_visible()
                )
            )
        self.main_window.menu_manager.toggle_toolbar_action.setChecked(
            toolbar_manager.any_toolbar_visible()
        )

        image_viewer.zoom.connect(self.main_window.zoom)
        toolbar_manager.main_viewer_controls_host_toggle_action.triggered.connect(
            self.main_window.toggle_main_viewer_controls_attachment
        )
        if getattr(toolbar_manager, 'reaction_controls_host_toggle_action', None) is not None:
            toolbar_manager.reaction_controls_host_toggle_action.triggered.connect(
                self.main_window.toggle_reaction_controls_attachment
            )
        toolbar_manager.zoom_fit_best_action.triggered.connect(
            lambda: (
                self.main_window.image_viewer.clear_saved_double_click_detail_zoom(),
                self.main_window.image_viewer.zoom_fit(),
            ))
        toolbar_manager.zoom_in_action.triggered.connect(
            lambda: self.main_window.image_viewer.zoom_in())
        toolbar_manager.zoom_original_action.triggered.connect(
            lambda: (
                self.main_window.image_viewer.clear_saved_double_click_detail_zoom(),
                self.main_window.image_viewer.zoom_original(),
            ))
        toolbar_manager.zoom_out_action.triggered.connect(
            lambda: self.main_window.image_viewer.zoom_out())
        if getattr(toolbar_manager, 'previous_media_action', None) is not None:
            toolbar_manager.previous_media_action.triggered.connect(
                self.main_window.image_list.go_to_previous_image
            )
        if getattr(toolbar_manager, 'next_media_action', None) is not None:
            toolbar_manager.next_media_action.triggered.connect(
                self.main_window.image_list.go_to_next_image
            )
        if getattr(toolbar_manager, 'main_viewer_fullscreen_action', None) is not None:
            toolbar_manager.main_viewer_fullscreen_action.triggered.connect(
                lambda: self.main_window.toggle_viewer_fullscreen(self.main_window.image_viewer)
            )
        if toolbar_manager.zoom_follow_mode_action is not None:
            toolbar_manager.zoom_follow_mode_action.triggered.connect(
                self.main_window.cycle_main_viewer_zoom_follow_mode)
        self._connect_reaction_controls(
            toolbar_manager.rating_widget,
            toolbar_manager.love_button,
            toolbar_manager.bomb_button,
        )
        reaction_overlay = getattr(self.main_window, '_reaction_controls_overlay', None)
        self._connect_reaction_controls(
            getattr(reaction_overlay, 'rating_widget', None),
            getattr(reaction_overlay, 'love_button', None),
            getattr(reaction_overlay, 'bomb_button', None),
        )

        toolbar_manager.add_action_group.triggered.connect(
            lambda action: image_viewer.add_marking(
                ImageMarking.NONE if not action.isChecked() else
                ImageMarking.CROP if action == toolbar_manager.add_crop_action else
                ImageMarking.HINT if action == toolbar_manager.add_hint_action else
                ImageMarking.EXCLUDE if action == toolbar_manager.add_exclude_action else
                ImageMarking.INCLUDE))

        image_viewer.marking.connect(lambda marking:
            toolbar_manager.add_crop_action.setChecked(True) if marking == ImageMarking.CROP else
            toolbar_manager.add_hint_action.setChecked(True) if marking == ImageMarking.HINT else
            toolbar_manager.add_exclude_action.setChecked(True) if marking == ImageMarking.EXCLUDE else
            toolbar_manager.add_include_action.setChecked(True) if marking == ImageMarking.INCLUDE else
            toolbar_manager.add_action_group.checkedAction() and
                toolbar_manager.add_action_group.checkedAction().setChecked(False))

        image_viewer.scene.selectionChanged.connect(lambda:
            self.main_window.is_running and toolbar_manager.add_toggle_marking_action.setEnabled(
                image_viewer.get_selected_type() not in [ImageMarking.NONE,
                                                              ImageMarking.CROP]))

        image_viewer.accept_crop_addition.connect(toolbar_manager.add_crop_action.setEnabled)
        # Enable/disable apply crop button based on whether crop exists (inverse of add_crop)
        image_viewer.accept_crop_addition.connect(
            lambda can_add: toolbar_manager.apply_crop_btn.setEnabled(not can_add))
        # Connect apply crop button to the apply_crop_to_file method
        toolbar_manager.apply_crop_btn.clicked.connect(image_viewer.apply_crop_to_file)

        image_viewer.scene.selectionChanged.connect(lambda:
            self.main_window.is_running and toolbar_manager.delete_marking_action.setEnabled(
                image_viewer.get_selected_type() != ImageMarking.NONE))

        toolbar_manager.delete_marking_action.triggered.connect(lambda: image_viewer.delete_markings())
        toolbar_manager.add_show_marking_action.toggled.connect(image_viewer.show_marking)
        toolbar_manager.add_show_marking_action.toggled.connect(toolbar_manager.add_action_group.setEnabled)
        toolbar_manager.add_show_marking_action.toggled.connect(lambda toggled:
                toolbar_manager.add_toggle_marking_action.setEnabled(toggled and
                    image_viewer.get_selected_type() != ImageMarking.NONE))
        toolbar_manager.add_show_marking_action.toggled.connect(toolbar_manager.add_show_labels_action.setEnabled)
        toolbar_manager.add_show_marking_action.toggled.connect(toolbar_manager.add_show_marking_latent_action.setEnabled)
        toolbar_manager.add_toggle_marking_action.triggered.connect(lambda: image_viewer.change_marking())
        toolbar_manager.add_show_labels_action.toggled.connect(image_viewer.show_label)
        toolbar_manager.add_show_marking_latent_action.toggled.connect(image_viewer.show_marking_latent)

        # Rating stars
        image_viewer.rating_changed.connect(
            lambda *_args: self.main_window._sync_rating_controls_from_viewer(image_viewer)
        )
        image_viewer.reaction_flags_changed.connect(
            lambda *_args: self.main_window._sync_rating_controls_from_viewer(image_viewer)
        )
        image_viewer.zoom_follow_mode_changed.connect(
            lambda mode: self.main_window.sync_zoom_follow_mode_button(image_viewer)
        )

    def _connect_reaction_controls(self, rating_widget, love_button, bomb_button):
        """Connect one set of rating/reaction widgets to the shared handlers."""
        if rating_widget is not None:
            rating_widget.rating_selected.connect(
                lambda stars, event: self.main_window.set_rating(float(stars) / 5.0, True, event)
            )
        if love_button is not None:
            love_button.filter_requested.connect(
                self.main_window.apply_reaction_filter
            )
            love_button.toggled.connect(
                lambda checked: self.main_window.set_reactions(
                    bool(checked),
                    None,
                    True,
                    changed_kind='love',
                )
            )
        if bomb_button is not None:
            bomb_button.filter_requested.connect(
                self.main_window.apply_reaction_filter
            )
            bomb_button.toggled.connect(
                lambda checked: self.main_window.set_reactions(
                    None,
                    bool(checked),
                    True,
                    changed_kind='bomb',
                )
            )

    def connect_image_list_signals(self):
        """Connect image list-related signals."""
        image_list = self.main_window.image_list
        image_list_model = self.main_window.image_list_model
        proxy_image_list_model = self.main_window.proxy_image_list_model
        image_tags_editor = self.main_window.image_tags_editor
        tag_counter_model = self.main_window.tag_counter_model
        image_list_selection_model = self.main_window.image_list_selection_model
        image_viewer = self.main_window.image_viewer
        menu_manager = self.main_window.menu_manager

        image_list.filter_line_edit.textChanged.connect(
            self.main_window.set_image_list_filter)
        image_list.filter_line_edit.apply_requested.connect(
            self.main_window.apply_image_list_filter_now)
        image_list.media_type_combo_box.currentTextChanged.connect(
            lambda _: self.main_window.delayed_filter())
        image_list_selection_model.currentChanged.connect(
            self.main_window.save_image_index)
        def safe_update_index_label(current, previous):
            if self.main_window._should_suppress_transient_drag_selection(current):
                return
            image_list.update_image_index_label(current)
        image_list_selection_model.currentChanged.connect(
            safe_update_index_label)
        def safe_load_image(current, previous):
            try:
                if self.main_window._should_suppress_transient_restore_index(current):
                    return
                if self.main_window._should_suppress_transient_drag_selection(current):
                    return
                # Post-click freeze: ignore recalc-driven selection mutations.
                import time as _t
                view = self.main_window.image_list.list_view
                if _t.time() < float(getattr(view, '_user_click_selection_frozen_until', 0.0) or 0.0):
                    return
                if current.isValid():
                    self.main_window.get_selection_target_viewer().load_image(current)
            except Exception as e:
                print(f"[SIGNAL] ERROR in currentChanged->load_image: {e}")
                import traceback
                traceback.print_exc()

        image_list_selection_model.currentChanged.connect(safe_load_image)
        def safe_load_tags(current, previous):
            if self.main_window._should_suppress_transient_drag_selection(current):
                return
            import time as _t
            view = self.main_window.image_list.list_view
            if _t.time() < float(getattr(view, '_user_click_selection_frozen_until', 0.0) or 0.0):
                return
            image_tags_editor.load_image_tags(current)
        image_list_selection_model.currentChanged.connect(safe_load_tags)
        image_list_selection_model.selectionChanged.connect(
            lambda *_: self.main_window._sync_rating_controls_from_context()
        )
        image_list_selection_model.currentChanged.connect(
            self.main_window._sync_rating_controls_from_context
        )
        image_list_model.modelReset.connect(self._update_tag_counts)
        image_list_model.modelReset.connect(self._update_delete_button_visibility)
        image_list_model.enrichment_complete.connect(self._update_tag_counts)
        image_list_model.dataChanged.connect(lambda *args: self._update_tag_counts())
        image_list_model.dataChanged.connect(
            image_tags_editor.reload_image_tags_if_changed)
        def refresh_viewer_on_data_change(start: QModelIndex, end: QModelIndex, roles):
            """Reload viewer only for the live current selection to avoid stale-index crashes."""
            try:
                target_viewer = self.main_window.get_selection_target_viewer()
                if target_viewer is None:
                    return
                if getattr(target_viewer, "_viewer_model_resetting", False):
                    return
                current = image_list_selection_model.currentIndex()
                if not current.isValid():
                    return
                if current.model() is not proxy_image_list_model:
                    return
                current_row = current.row()
                if start.isValid() and end.isValid() and start.row() <= current_row <= end.row():
                    target_viewer.load_image(current, False)
            except Exception as e:
                print(f"[SIGNAL] ERROR in dataChanged->load_image: {e}")

        image_list_model.dataChanged.connect(refresh_viewer_on_data_change)
        image_list_model.sidecar_reaction_migration_applied.connect(
            lambda _count: self.main_window._refresh_reaction_sort_if_active()
        )
        image_list_model.update_undo_and_redo_actions_requested.connect(
            menu_manager.update_undo_and_redo_actions)
        image_list_model.total_count_changed.connect(
            lambda _count: image_list.update_image_index_label(
                image_list.list_view.currentIndex()))
        proxy_image_list_model.filter_changed.connect(
            lambda: image_list.update_image_index_label(
                image_list.list_view.currentIndex()))
        proxy_image_list_model.filter_changed.connect(
            lambda: tag_counter_model.count_tags_filtered(
                proxy_image_list_model.get_list() if
                len(proxy_image_list_model.filter or [])>0 else None))
        # Connect deletion marking signals
        image_list.deletion_marking_changed.connect(self._update_delete_button_visibility)

        image_list.list_view.directory_reload_requested.connect(
            self.main_window.reload_directory)
        image_list.directory_reload_requested.connect(
            self.main_window.reload_directory)
        image_list.list_view.tags_paste_requested.connect(
            image_list_model.add_tags)
        image_list.visibilityChanged.connect(
            lambda: menu_manager.toggle_image_list_action.setChecked(
                image_list.isVisible()))
        image_viewer.crop_changed.connect(image_list.list_view.show_crop_size)
        image_viewer.directory_reload_requested.connect(
            self.main_window.reload_directory)

    def connect_image_tags_editor_signals(self):
        """Connect image tags editor-related signals."""
        image_tag_list_model = self.main_window.image_tag_list_model
        image_tags_editor = self.main_window.image_tags_editor
        image_list_model = self.main_window.image_list_model
        menu_manager = self.main_window.menu_manager

        image_tag_list_model.modelReset.connect(self.main_window.update_image_tags)
        image_tag_list_model.dataChanged.connect(self.main_window.update_image_tags)
        image_tag_list_model.rowsMoved.connect(self.main_window.update_image_tags)
        image_tags_editor.visibilityChanged.connect(
            lambda: menu_manager.toggle_image_tags_editor_action.setChecked(
                image_tags_editor.isVisible()))
        image_tags_editor.tag_input_box.tags_addition_requested.connect(
            image_list_model.add_tags)

    def connect_all_tags_editor_signals(self):
        """Connect all tags editor-related signals."""
        all_tags_editor = self.main_window.all_tags_editor
        image_list = self.main_window.image_list
        tag_counter_model = self.main_window.tag_counter_model
        image_list_model = self.main_window.image_list_model
        menu_manager = self.main_window.menu_manager

        all_tags_editor.clear_filter_button.clicked.connect(
            image_list.filter_line_edit.clear)
        tag_counter_model.tags_renaming_requested.connect(
            image_list_model.rename_tags)
        tag_counter_model.tags_renaming_requested.connect(
            image_list.filter_line_edit.clear)
        all_tags_editor.all_tags_list.image_list_filter_requested.connect(
            self.main_window.set_image_list_filter_text)
        all_tags_editor.all_tags_list.tag_addition_requested.connect(
            self.main_window.add_tag_to_selected_images)
        all_tags_editor.all_tags_list.tags_deletion_requested.connect(
            image_list_model.delete_tags)
        all_tags_editor.all_tags_list.tags_deletion_requested.connect(
            image_list.filter_line_edit.clear)
        all_tags_editor.visibilityChanged.connect(
            lambda: menu_manager.toggle_all_tags_editor_action.setChecked(
                all_tags_editor.isVisible()))

    def connect_auto_captioner_signals(self):
        """Connect auto captioner-related signals."""
        auto_captioner = self.main_window.auto_captioner
        image_list_model = self.main_window.image_list_model
        image_tags_editor = self.main_window.image_tags_editor
        menu_manager = self.main_window.menu_manager

        auto_captioner.caption_generated.connect(
            lambda image_index, _, tags:
            image_list_model.update_image_tags(image_index, tags))
        auto_captioner.caption_generated.connect(
            lambda image_index, *_:
            image_tags_editor.reload_image_tags_if_changed(image_index, image_index))
        auto_captioner.visibilityChanged.connect(
            lambda: menu_manager.toggle_auto_captioner_action.setChecked(
                auto_captioner.isVisible()))

    def connect_auto_markings_signals(self):
        """Connect auto markings-related signals."""
        auto_markings = self.main_window.auto_markings
        image_list_model = self.main_window.image_list_model
        menu_manager = self.main_window.menu_manager

        auto_markings.marking_generated.connect(
            lambda image_index, markings:
            image_list_model.add_image_markings(image_index, markings))
        auto_markings.visibilityChanged.connect(
            lambda: menu_manager.toggle_auto_markings_action.setChecked(
                auto_markings.isVisible()))

    def connect_video_controls_signals(self):
        """Connect video player and controls signals."""
        video_player = self.main_window.image_viewer.video_player
        video_controls = self.main_window.image_viewer.video_controls
        toolbar_manager = self.main_window.toolbar_manager
        video_editing_controller = self.main_window.video_editing_controller

        # Connect video controls to video player
        def on_play_pause_requested():
            """Handle manual play/pause toggle from user."""
            self.main_window.toggle_viewer_play_pause(self.main_window.image_viewer)

        video_controls.play_pause_requested.connect(on_play_pause_requested)
        video_controls.stop_requested.connect(video_player.stop)
        video_controls.frame_changed.connect(video_player.seek_to_frame)
        video_controls.timeline_slider.scrub_started.connect(video_player.begin_timeline_scrub)
        video_controls.timeline_slider.sliderReleased.connect(video_player.end_timeline_scrub)
        # Connect marker preview - seeks video without updating controls
        video_controls.marker_preview_requested.connect(video_player.seek_to_frame)
        video_controls.skip_back_btn.clicked.connect(
            lambda checked=False: self.main_window.image_viewer.handle_video_controls_skip_button_step('backward')
        )
        video_controls.skip_forward_btn.clicked.connect(
            lambda checked=False: self.main_window.image_viewer.handle_video_controls_skip_button_step('forward')
        )

        # Connect video player updates to video controls
        video_player.frame_changed.connect(
            lambda frame, time_ms: self.main_window._queue_video_controls_update(
                self.main_window.image_viewer, frame, time_ms
            )
        )
        video_player.playback_started.connect(
            lambda: video_controls.set_playing(True)
        )
        video_player.playback_paused.connect(
            lambda: video_controls.set_playing(False)
        )
        video_player.playback_finished.connect(
            lambda: video_controls.set_playing(False)
        )

        # Connect loop controls
        video_controls.loop_toggled.connect(lambda enabled: self._update_loop_state())
        video_controls.loop_start_set.connect(lambda: self._update_loop_state())
        video_controls.loop_end_set.connect(lambda: self._update_loop_state())
        video_controls.loop_reset.connect(
            lambda: self._update_loop_state())

        # Connect speed control
        video_controls.speed_changed.connect(video_player.set_playback_speed)

        # Connect mute control
        video_controls.mute_toggled.connect(
            lambda muted: video_player.set_muted(muted))

        # Connect toolbar video editing controls
        toolbar_manager.fixed_marker_size_spinbox.valueChanged.connect(
            lambda value: self._on_marker_size_changed(value))
        # Initialize video_controls.fixed_marker_size from saved settings
        video_controls.fixed_marker_size = toolbar_manager.fixed_marker_size_spinbox.value()

        toolbar_manager.always_show_controls_action.triggered.connect(
            toolbar_manager.cycle_main_viewer_video_controls_visibility_mode
        )

        # Connect video editing buttons
        toolbar_manager.extract_range_action.triggered.connect(
            video_editing_controller.extract_video_range)
        toolbar_manager.extract_range_rough_btn.clicked.connect(
            video_editing_controller.extract_video_range_rough)
        toolbar_manager.screenshot_frame_btn.clicked.connect(
            lambda: video_editing_controller.capture_current_video_frame()
        )
        toolbar_manager.remove_range_action.triggered.connect(
            video_editing_controller.remove_video_range)
        toolbar_manager.remove_frame_action.triggered.connect(
            video_editing_controller.remove_video_frame)
        toolbar_manager.repeat_frame_action.triggered.connect(
            video_editing_controller.repeat_video_frame)
        video_controls.screenshot_requested.connect(
            lambda: video_editing_controller.capture_current_video_frame(
                viewer=self.main_window.image_viewer
            )
        )
        toolbar_manager.fix_frame_count_btn.clicked.connect(
            video_editing_controller.fix_video_frame_count)
        toolbar_manager.fix_all_folder_btn.clicked.connect(
            video_editing_controller.fix_all_folder_frame_count)
        toolbar_manager.fix_sar_btn.clicked.connect(
            video_editing_controller.fix_sar_selected)
        toolbar_manager.fix_all_sar_btn.clicked.connect(
            video_editing_controller.fix_all_sar_folder)
        toolbar_manager.apply_speed_btn.clicked.connect(
            video_editing_controller.apply_speed_change)
        toolbar_manager.change_fps_btn.clicked.connect(
            video_editing_controller.change_fps)

    def _update_loop_state(self):
        """Update video player loop state from controls."""
        video_controls = self.main_window.image_viewer.video_controls
        video_player = self.main_window.image_viewer.video_player

        is_looping = bool(video_controls.is_looping)
        loop_range = video_controls.get_loop_range()

        if not is_looping:
            video_player.set_loop(False, None, None)
            return

        if loop_range:
            video_player.set_loop(True, loop_range[0], loop_range[1])
        else:
            # No markers: enable full-video loop mode.
            video_player.set_loop(True, None, None)

    def _skip_video(self, backward: bool):
        """Skip 1 second backward or forward in video."""
        video_player = self.main_window.image_viewer.video_player
        fps = video_player.get_fps()
        if fps == 0:
            return

        frame_offset = int(fps)
        current_frame = video_player.get_current_frame_number()

        if backward:
            new_frame = max(0, current_frame - frame_offset)
        else:
            new_frame = min(video_player.get_total_frames() - 1,
                          current_frame + frame_offset)

        video_player.seek_to_frame(new_frame)

    def _on_marker_size_changed(self, value):
        """Handle marker size changes and save to settings."""
        video_controls = self.main_window.image_viewer.video_controls
        setattr(video_controls, 'fixed_marker_size', value)
        settings.setValue('fixed_marker_size', value)

    def _update_delete_button_visibility(self):
        """Show/hide delete marked menu based on whether any images are marked."""
        if hasattr(self.main_window, 'image_list') and hasattr(self.main_window, 'menu_manager'):
            count = self.main_window.image_list.get_marked_for_deletion_count()
            self.main_window.menu_manager.update_delete_marked_menu(count)

    def _update_tag_counts(self):
        """Update tag counts based on current model mode (paginated (DB) vs normal)."""
        image_list_model = self.main_window.image_list_model
        tag_counter_model = self.main_window.tag_counter_model
        
        if image_list_model.is_paginated:
             # Use DB stats for efficiency and full coverage
             stats = image_list_model.get_all_tags_stats()
             tag_counter_model.set_tags_from_db(stats)
        else:
             # Regular in-memory counting
             tag_counter_model.count_tags(image_list_model.get_all_loaded_images())
