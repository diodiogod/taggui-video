"""Manager for connecting signals in main window."""

from PySide6.QtCore import Qt, Slot, QModelIndex
from widgets.image_viewer import ImageMarking
from utils.settings import settings


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

        toolbar_manager.toolbar.visibilityChanged.connect(
            lambda: self.main_window.menu_manager.toggle_toolbar_action.setChecked(
                toolbar_manager.toolbar.isVisible()))

        image_viewer.zoom.connect(self.main_window.zoom)
        toolbar_manager.zoom_fit_best_action.triggered.connect(image_viewer.zoom_fit)
        toolbar_manager.zoom_in_action.triggered.connect(image_viewer.zoom_in)
        toolbar_manager.zoom_original_action.triggered.connect(image_viewer.zoom_original)
        toolbar_manager.zoom_out_action.triggered.connect(image_viewer.zoom_out)

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
        image_viewer.rating_changed.connect(self.main_window.set_rating)

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
        image_list_selection_model.currentChanged.connect(
            self.main_window.save_image_index)
        image_list_selection_model.currentChanged.connect(
            image_list.update_image_index_label)
        def safe_load_image(current, previous):
            try:
                if current.isValid():
                    image_viewer.load_image(current)
            except Exception as e:
                print(f"[SIGNAL] ERROR in currentChanged->load_image: {e}")
                import traceback
                traceback.print_exc()

        image_list_selection_model.currentChanged.connect(safe_load_image)
        image_list_selection_model.currentChanged.connect(
            image_tags_editor.load_image_tags)
        image_list_model.modelReset.connect(self._update_tag_counts)
        image_list_model.dataChanged.connect(lambda: self._update_tag_counts())
        image_list_model.dataChanged.connect(
            image_tags_editor.reload_image_tags_if_changed)
        image_list_model.dataChanged.connect(
            lambda start, end, roles:
                image_viewer.load_image(image_viewer.proxy_image_index, False)
                if (start.row() <= image_viewer.proxy_image_index.row() <= end.row()) else 0)
        image_list_model.update_undo_and_redo_actions_requested.connect(
            menu_manager.update_undo_and_redo_actions)
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
            video_player.toggle_play_pause()
            video_controls.set_playing(video_player.is_playing, update_auto_play=True)

        video_controls.play_pause_requested.connect(on_play_pause_requested)
        video_controls.stop_requested.connect(video_player.stop)
        video_controls.frame_changed.connect(video_player.seek_to_frame)
        # Connect marker preview - seeks video without updating controls
        video_controls.marker_preview_requested.connect(video_player.seek_to_frame)
        video_controls.skip_backward_requested.connect(
            lambda: self._skip_video(backward=True))
        video_controls.skip_forward_requested.connect(
            lambda: self._skip_video(backward=False))

        # Connect video player updates to video controls
        video_player.frame_changed.connect(video_controls.update_position)
        video_player.frame_changed.connect(
            lambda frame, time_ms: video_controls.set_playing(video_player.is_playing))

        # Connect loop controls
        video_controls.loop_toggled.connect(lambda enabled: self._update_loop_state())
        video_controls.loop_start_set.connect(lambda: self._update_loop_state())
        video_controls.loop_end_set.connect(lambda: self._update_loop_state())
        video_controls.loop_reset.connect(
            lambda: video_player.set_loop(False, None, None))

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

        # Always show controls toggle
        def on_always_show_toggled(checked):
            self.main_window.image_viewer.set_always_show_controls(checked)
            settings.setValue('video_always_show_controls', checked)

        toolbar_manager.always_show_controls_btn.toggled.connect(on_always_show_toggled)

        # Connect video editing buttons
        toolbar_manager.extract_range_action.triggered.connect(
            video_editing_controller.extract_video_range)
        toolbar_manager.extract_range_rough_btn.clicked.connect(
            video_editing_controller.extract_video_range_rough)
        toolbar_manager.remove_range_action.triggered.connect(
            video_editing_controller.remove_video_range)
        toolbar_manager.remove_frame_action.triggered.connect(
            video_editing_controller.remove_video_frame)
        toolbar_manager.repeat_frame_action.triggered.connect(
            video_editing_controller.repeat_video_frame)
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

        if not video_controls.is_looping:
            video_player.set_loop(False, None, None)
            return

        loop_range = video_controls.get_loop_range()
        if loop_range:
            video_player.set_loop(True, loop_range[0], loop_range[1])
        else:
            total_frames = video_player.get_total_frames()
            if total_frames > 0:
                video_player.set_loop(True, 0, total_frames - 1)
            else:
                video_player.set_loop(False, None, None)

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
