"""Manager for main window toolbar setup."""

from PySide6.QtWidgets import QToolBar, QPushButton, QWidget, QHBoxLayout, QLabel, QSpinBox, QMenu, QSizePolicy
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QTimer

from utils.icons import (
    create_add_box_icon,
    create_apply_crop_icon,
    create_fullscreen_icon,
    toggle_marking_icon,
    show_markings_icon,
    show_labels_icon,
    show_marking_latent_icon,
)
from utils.settings import (
    settings,
    load_video_controls_visibility_mode,
    normalize_video_controls_visibility_mode,
    persist_video_controls_visibility_mode,
    VIDEO_CONTROLS_VISIBILITY_ALWAYS,
    VIDEO_CONTROLS_VISIBILITY_AUTO,
    VIDEO_CONTROLS_VISIBILITY_OFF,
)
from widgets.main_viewer_controls_widget import MainViewerControlsWidget
from widgets.reaction_controls_widget import ReactionControlsWidget


class ToolbarManager:
    """Manages toolbar creation and setup."""

    DEFAULT_TOOLBAR_ORDER = (
        'viewer',
        'marking',
        'marker',
        'video_edit',
        'video_fix',
        'rating',
    )

    def __init__(self, main_window):
        """Initialize toolbar manager."""
        self.main_window = main_window
        self.toolbar = None
        self.toolbars = {}
        self.main_viewer_controls_host_toggle_action = None
        self.reaction_controls_host_toggle_action = None
        self.previous_media_action = None
        self._action_buttons = {}
        self.next_media_action = None
        self.main_viewer_fullscreen_action = None
        self.zoom_fit_best_action = None
        self.zoom_in_action = None
        self.zoom_original_action = None
        self.zoom_out_action = None
        self.add_action_group = None
        self.add_crop_action = None
        self.apply_crop_btn = None
        self.add_hint_action = None
        self.add_exclude_action = None
        self.add_include_action = None
        self.delete_marking_action = None
        self.add_toggle_marking_action = None
        self.add_show_marking_action = None
        self.add_show_labels_action = None
        self.add_show_marking_latent_action = None
        self.always_show_controls_action = None
        self.zoom_follow_mode_action = None
        self.fixed_marker_size_spinbox = None
        self.extract_range_action = None
        self.screenshot_frame_btn = None
        self.extract_range_rough_btn = None
        self.remove_range_action = None
        self.remove_frame_action = None
        self.repeat_frame_action = None
        self.fix_frame_count_btn = None
        self.fix_all_folder_btn = None
        self.fix_sar_btn = None
        self.fix_all_sar_btn = None
        self.apply_speed_btn = None
        self.change_fps_btn = None
        self.rating = 0
        self.reaction_controls_widget = None
        self.rating_widget = None
        self.love_button = None
        self.bomb_button = None
        self.delete_marked_btn = None
        self.delete_marked_menu = None

    def create_toolbar(self):
        """Create and setup grouped toolbars for native Qt reordering."""
        viewer_toolbar = self._create_toolbar_group('Main Viewer Controls', key='viewer')
        marking_toolbar = self._create_toolbar_group('Marking toolbar', key='marking')
        marker_toolbar = self._create_toolbar_group('Marker toolbar', key='marker')
        video_edit_toolbar = self._create_toolbar_group('Video edit toolbar', key='video_edit')
        video_fix_toolbar = self._create_toolbar_group('Video tools toolbar', key='video_fix')
        rating_toolbar = self._create_toolbar_group('Rating toolbar', key='rating')

        self.toolbar = viewer_toolbar

        self._create_viewer_controls(viewer_toolbar)
        self._create_marking_controls(marking_toolbar)
        self._create_marker_controls(marker_toolbar)
        self._create_video_edit_controls(video_edit_toolbar)
        self._create_video_fix_controls(video_fix_toolbar)
        self._create_rating_stars(rating_toolbar)

        return viewer_toolbar

    def _create_toolbar_group(self, title: str, *, key: str) -> QToolBar:
        """Create a movable toolbar group tracked by semantic key."""
        toolbar = QToolBar(title, self.main_window)
        toolbar.setObjectName(title)
        toolbar.setProperty('toolbar_group_key', key)
        toolbar.setFloatable(True)
        toolbar.setMovable(True)
        toolbar.setAllowedAreas(
            Qt.ToolBarArea.TopToolBarArea | Qt.ToolBarArea.BottomToolBarArea
        )
        if key == 'rating':
            toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.toolbars[key] = toolbar
        return toolbar

    def get_toolbars(self) -> list[QToolBar]:
        """Return grouped toolbars in creation order."""
        return list(self.toolbars.values())

    def set_toolbars_visible(self, visible: bool):
        """Show or hide all grouped toolbars together."""
        for toolbar in self.get_toolbars():
            toolbar.setVisible(bool(visible))

    def any_toolbar_visible(self) -> bool:
        """Return True when at least one toolbar group is visible."""
        toolbars = self.get_toolbars()
        return any(toolbar.isVisible() for toolbar in toolbars)

    def reset_toolbars_layout(self):
        """Restore the default toolbar order, docking, and visibility."""
        for toolbar in self.get_toolbars():
            try:
                if toolbar.isFloating():
                    toolbar.setFloating(False)
            except Exception:
                pass
            self.main_window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
            toolbar.setVisible(True)

        ordered_toolbars = [
            self.toolbars[key]
            for key in self.DEFAULT_TOOLBAR_ORDER
            if key in self.toolbars
        ]
        self._set_toolbar_sequence(ordered_toolbars)

        for toolbar in ordered_toolbars:
            try:
                self.main_window.removeToolBarBreak(toolbar)
            except Exception:
                pass

        self._snap_default_toolbar_layout(ordered_toolbars)

    def _set_toolbar_sequence(self, ordered_toolbars: list[QToolBar]):
        """Normalize toolbar order within the top toolbar area."""
        for toolbar in ordered_toolbars:
            if self.main_window.toolBarArea(toolbar) != Qt.ToolBarArea.TopToolBarArea:
                self.main_window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        for index in range(len(ordered_toolbars) - 2, -1, -1):
            before = ordered_toolbars[index + 1]
            toolbar = ordered_toolbars[index]
            self.main_window.insertToolBar(before, toolbar)

    def _snap_default_toolbar_layout(self, ordered_toolbars: list[QToolBar]):
        """Pack non-rating toolbars to their real content width for the default layout."""
        measured_widths = {}
        for toolbar in ordered_toolbars:
            group_key = str(toolbar.property('toolbar_group_key') or '')
            if group_key == 'rating':
                continue
            measured_widths[toolbar] = self._measure_toolbar_content_width(toolbar)
            toolbar.setMinimumWidth(measured_widths[toolbar])
            toolbar.setMaximumWidth(measured_widths[toolbar])

        rating_toolbar = self.toolbars.get('rating')
        if rating_toolbar is not None:
            rating_toolbar.setMinimumWidth(0)
            rating_toolbar.setMaximumWidth(16777215)

        def _clear_width_clamps():
            for toolbar in measured_widths:
                toolbar.setMinimumWidth(0)
                toolbar.setMaximumWidth(16777215)

        QTimer.singleShot(0, _clear_width_clamps)

    def _measure_toolbar_content_width(self, toolbar: QToolBar) -> int:
        """Measure a docked toolbar using real child size hints."""
        toolbar.ensurePolished()
        hint_width = int(toolbar.sizeHint().width() or 0)
        widget_width = 0
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if widget is None:
                widget_width += 34
                continue
            widget.ensurePolished()
            width = int(widget.sizeHint().width() or widget.minimumSizeHint().width() or 0)
            if width <= 0:
                width = 34
            widget_width += width + 6
        return max(60, max(hint_width, widget_width) + 8)

    def _add_toolbar_action_button(self, toolbar: QToolBar, action: QAction, *, role: str = "viewer_action"):
        """Add a compact action-backed button to the toolbar."""
        from PySide6.QtWidgets import QToolButton

        button = QToolButton(toolbar)
        button.setDefaultAction(action)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("toolbarRole", role)
        if role == "host_toggle":
            button.setFixedSize(22, 32)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        else:
            button.setFixedSize(32, 32)
            if action.icon().isNull():
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            else:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setStyleSheet("""
            QToolButton[toolbarRole="viewer_action"] {
                font-size: 16px;
                font-weight: 700;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2b2b2b;
                color: #f8fafc;
                padding: 0px;
            }
            QToolButton[toolbarRole="viewer_action"]:hover {
                border-color: #777;
                background-color: #353535;
            }
            QToolButton[toolbarRole="viewer_action"]:checked {
                border-color: #4CAF50;
                background-color: #2d5a2d;
            }
            QToolButton[toolbarRole="viewer_action"][videoControlsVisibilityMode="always"] {
                border-color: #67c587;
                background-color: #294033;
                color: #9ae6b4;
            }
            QToolButton[toolbarRole="viewer_action"][videoControlsVisibilityMode="auto"] {
                border-color: #8d98a8;
                background-color: #424a57;
                color: #edf2f7;
            }
            QToolButton[toolbarRole="viewer_action"][videoControlsVisibilityMode="off"] {
                border-color: #d98282;
                background-color: #4d2424;
                color: #fecaca;
            }
            QToolButton[toolbarRole="host_toggle"] {
                font-size: 11px;
                font-weight: 700;
                border: 1px solid #616874;
                border-radius: 4px;
                background-color: #353b45;
                color: #dfe6ef;
                padding: 0px;
            }
            QToolButton[toolbarRole="host_toggle"]:hover {
                border-color: #838d9c;
                background-color: #414854;
                color: #f8fafc;
            }
            QToolButton[toolbarRole="host_toggle"]:pressed {
                background-color: #2c313a;
            }
            QToolButton[toolbarRole="host_toggle"]:checked {
                border-color: #67c587;
                background-color: #294033;
                color: #9ae6b4;
            }
        """)
        toolbar.addWidget(button)
        self.register_action_button(action, button)
        return button

    def register_action_button(self, action: QAction, button):
        if action is None or button is None:
            return
        self._action_buttons.setdefault(action, []).append(button)
        if action is self.always_show_controls_action:
            self._apply_video_controls_visibility_mode_to_button(
                button,
                normalize_video_controls_visibility_mode(action.data()),
            )

    def _apply_video_controls_visibility_mode_to_button(self, button, mode: str):
        mode = normalize_video_controls_visibility_mode(mode)
        button.setProperty("videoControlsVisibilityMode", mode)
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)
        button.update()

    def set_video_controls_visibility_action_mode(self, mode: str):
        mode = normalize_video_controls_visibility_mode(mode)
        action = self.always_show_controls_action
        if action is None:
            return
        action.setData(mode)
        action.setText('👁')
        tooltip_map = {
            VIDEO_CONTROLS_VISIBILITY_ALWAYS: 'Video controls: always shown',
            VIDEO_CONTROLS_VISIBILITY_AUTO: 'Video controls: auto-hide',
            VIDEO_CONTROLS_VISIBILITY_OFF: 'Video controls: always hidden',
        }
        action.setToolTip(tooltip_map.get(mode, tooltip_map[VIDEO_CONTROLS_VISIBILITY_AUTO]))
        for button in self._action_buttons.get(action, []):
            self._apply_video_controls_visibility_mode_to_button(button, mode)

    def cycle_main_viewer_video_controls_visibility_mode(self, _checked: bool = False):
        current_mode = normalize_video_controls_visibility_mode(
            self.always_show_controls_action.data()
            if self.always_show_controls_action is not None
            else load_video_controls_visibility_mode()
        )
        next_mode_map = {
            VIDEO_CONTROLS_VISIBILITY_ALWAYS: VIDEO_CONTROLS_VISIBILITY_AUTO,
            VIDEO_CONTROLS_VISIBILITY_AUTO: VIDEO_CONTROLS_VISIBILITY_OFF,
            VIDEO_CONTROLS_VISIBILITY_OFF: VIDEO_CONTROLS_VISIBILITY_ALWAYS,
        }
        next_mode = next_mode_map.get(current_mode, VIDEO_CONTROLS_VISIBILITY_AUTO)
        persist_video_controls_visibility_mode(next_mode)
        self.set_video_controls_visibility_action_mode(next_mode)
        viewer = getattr(self.main_window, 'image_viewer', None)
        if viewer is not None:
            viewer.set_video_controls_visibility_mode(next_mode)

    def _create_viewer_controls(self, toolbar: QToolBar):
        """Create the combined main-viewer controls group."""
        self.main_viewer_controls_host_toggle_action = QAction('⋮', self.main_window)
        self.main_viewer_controls_host_toggle_action.setCheckable(True)
        self.main_viewer_controls_host_toggle_action.setToolTip(
            'Attach controls to the main viewer overlay'
        )
        self._add_toolbar_action_button(
            toolbar,
            self.main_viewer_controls_host_toggle_action,
            role="host_toggle",
        )

        self.previous_media_action = QAction(
            QIcon.fromTheme('go-previous'),
            'Previous media',
            self.main_window,
        )
        self.previous_media_action.setToolTip('Previous image or video')
        self._add_toolbar_action_button(toolbar, self.previous_media_action)

        self.next_media_action = QAction(
            QIcon.fromTheme('go-next'),
            'Next media',
            self.main_window,
        )
        self.next_media_action.setToolTip('Next image or video')
        self._add_toolbar_action_button(toolbar, self.next_media_action)

        self.main_viewer_fullscreen_action = QAction(
            create_fullscreen_icon(exit_fullscreen=False),
            'Fullscreen',
            self.main_window,
        )
        self.main_viewer_fullscreen_action.setCheckable(True)
        self.main_viewer_fullscreen_action.setToolTip('Fullscreen (F)')
        self._add_toolbar_action_button(toolbar, self.main_viewer_fullscreen_action)

        self.zoom_fit_best_action = QAction(
            QIcon.fromTheme('zoom-fit-best'),
            'Zoom to fit',
            self.main_window,
        )
        self.zoom_fit_best_action.setCheckable(True)
        self._add_toolbar_action_button(toolbar, self.zoom_fit_best_action)

        self.zoom_in_action = QAction(
            QIcon.fromTheme('zoom-in'),
            'Zoom in',
            self.main_window,
        )
        self._add_toolbar_action_button(toolbar, self.zoom_in_action)

        self.zoom_original_action = QAction(
            QIcon.fromTheme('zoom-original'),
            'Original size',
            self.main_window,
        )
        self.zoom_original_action.setCheckable(True)
        self._add_toolbar_action_button(toolbar, self.zoom_original_action)

        self.zoom_out_action = QAction(
            QIcon.fromTheme('zoom-out'),
            'Zoom out',
            self.main_window,
        )
        self._add_toolbar_action_button(toolbar, self.zoom_out_action)

        self.always_show_controls_action = QAction('👁', self.main_window)
        self.always_show_controls_action.setCheckable(False)
        self._add_toolbar_action_button(toolbar, self.always_show_controls_action)
        self.set_video_controls_visibility_action_mode(load_video_controls_visibility_mode())

        self.zoom_follow_mode_action = QAction('⛶', self.main_window)
        self.zoom_follow_mode_action.setToolTip('Default: Per-image zoom behavior')
        self._add_toolbar_action_button(toolbar, self.zoom_follow_mode_action)
        self.set_zoom_follow_mode_button('default')

    def _create_marking_controls(self, toolbar: QToolBar):
        """Create marking toolbar actions."""
        self.add_action_group = QActionGroup(self.main_window)
        self.add_action_group.setExclusionPolicy(QActionGroup.ExclusiveOptional)

        self.add_crop_action = QAction(
            create_add_box_icon(Qt.blue),
            'Add crop',
            self.add_action_group,
        )
        self.add_crop_action.setCheckable(True)
        self.add_crop_action.setToolTip(
            'Add crop box (hold Shift while dragging to snap to bucket resolution)'
        )
        toolbar.addAction(self.add_crop_action)

        self.apply_crop_btn = QPushButton('✂')
        self.apply_crop_btn.setToolTip(
            'Apply crop to file (destructive, creates backup)'
        )
        self.apply_crop_btn.setMaximumWidth(32)
        self.apply_crop_btn.setMaximumHeight(32)
        self.apply_crop_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2b2b2b;
                padding: 2px;
            }
            QPushButton:hover {
                border-color: #2196F3;
                background-color: #353535;
            }
            QPushButton:disabled {
                color: #555;
                border-color: #333;
            }
        """)
        self.apply_crop_btn.setEnabled(False)
        toolbar.addWidget(self.apply_crop_btn)

        self.add_hint_action = QAction(
            create_add_box_icon(Qt.gray),
            'Add hint',
            self.add_action_group,
        )
        self.add_hint_action.setCheckable(True)
        toolbar.addAction(self.add_hint_action)

        self.add_exclude_action = QAction(
            create_add_box_icon(Qt.red),
            'Add exclude mask',
            self.add_action_group,
        )
        self.add_exclude_action.setCheckable(True)
        toolbar.addAction(self.add_exclude_action)

        self.add_include_action = QAction(
            create_add_box_icon(Qt.green),
            'Add include mask',
            self.add_action_group,
        )
        self.add_include_action.setCheckable(True)
        toolbar.addAction(self.add_include_action)

        self.delete_marking_action = QAction(
            QIcon.fromTheme('edit-delete'),
            'Delete marking',
            self.main_window,
        )
        self.delete_marking_action.setEnabled(False)
        toolbar.addAction(self.delete_marking_action)

        self.add_toggle_marking_action = QAction(
            toggle_marking_icon(),
            'Change marking type',
            self.main_window,
        )
        self.add_toggle_marking_action.setEnabled(False)
        toolbar.addAction(self.add_toggle_marking_action)

        self.add_show_marking_action = QAction(
            show_markings_icon(),
            'Show markings',
            self.main_window,
        )
        self.add_show_marking_action.setCheckable(True)
        self.add_show_marking_action.setChecked(True)
        toolbar.addAction(self.add_show_marking_action)

        self.add_show_labels_action = QAction(
            show_labels_icon(),
            'Show labels',
            self.main_window,
        )
        self.add_show_labels_action.setCheckable(True)
        self.add_show_labels_action.setChecked(True)
        toolbar.addAction(self.add_show_labels_action)

        self.add_show_marking_latent_action = QAction(
            show_marking_latent_icon(),
            'Show marking in latent space',
            self.main_window,
        )
        self.add_show_marking_latent_action.setCheckable(True)
        self.add_show_marking_latent_action.setChecked(True)
        toolbar.addAction(self.add_show_marking_latent_action)

    def _create_marker_controls(self, toolbar: QToolBar):
        """Create auto-marking toolbar controls."""
        marker_size_widget = QWidget()
        marker_size_layout = QHBoxLayout(marker_size_widget)
        marker_size_layout.setContentsMargins(4, 0, 4, 0)
        marker_size_layout.setSpacing(4)
        marker_size_label = QLabel('Marker size:')
        self.fixed_marker_size_spinbox = QSpinBox()
        self.fixed_marker_size_spinbox.setMinimum(0)
        self.fixed_marker_size_spinbox.setMaximum(9999)
        marker_size = settings.value('fixed_marker_size', defaultValue=0, type=int)
        self.fixed_marker_size_spinbox.setValue(marker_size)
        self.fixed_marker_size_spinbox.setSpecialValueText('Custom')
        self.fixed_marker_size_spinbox.setSuffix(' frames')
        self.fixed_marker_size_spinbox.setToolTip(
            'Fixed frame count for auto markers (0 = Custom allows manual marker setting)'
        )
        marker_size_layout.addWidget(marker_size_label)
        marker_size_layout.addWidget(self.fixed_marker_size_spinbox)
        toolbar.addWidget(marker_size_widget)

    def _create_video_edit_controls(self, toolbar: QToolBar):
        """Create video edit action toolbar controls."""
        self.screenshot_frame_btn = QPushButton('📸')
        self.screenshot_frame_btn.setToolTip('Screenshot current frame to image')
        self.screenshot_frame_btn.setMaximumWidth(32)
        self.screenshot_frame_btn.setMaximumHeight(32)
        self.screenshot_frame_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 60);
                border: 1px solid rgba(0, 0, 0, 150);
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 90);
            }
        """)
        toolbar.addWidget(self.screenshot_frame_btn)

        self.extract_range_rough_btn = QPushButton('🔑')
        self.extract_range_rough_btn.setToolTip(
            'Extract range* (ROUGH: fast keyframe cut, preserves quality, NOT frame-accurate)'
        )
        self.extract_range_rough_btn.setMaximumWidth(32)
        self.extract_range_rough_btn.setMaximumHeight(32)
        self.extract_range_rough_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: rgba(255, 165, 0, 60);
                border: 1px solid rgba(255, 165, 0, 150);
            }
            QPushButton:pressed {
                background-color: rgba(255, 165, 0, 90);
            }
        """)
        toolbar.addWidget(self.extract_range_rough_btn)

        self.extract_range_action = QAction(
            QIcon.fromTheme('document-save'),
            'Extract range (PRECISE: frame-accurate, slow, re-encodes)',
            self.main_window,
        )
        toolbar.addAction(self.extract_range_action)

        self.remove_range_action = QAction(
            QIcon.fromTheme('edit-cut'),
            'Remove range from video',
            self.main_window,
        )
        toolbar.addAction(self.remove_range_action)

        self.remove_frame_action = QAction(
            QIcon.fromTheme('edit-delete'),
            'Remove current frame',
            self.main_window,
        )
        toolbar.addAction(self.remove_frame_action)

        self.repeat_frame_action = QAction(
            QIcon.fromTheme('edit-copy'),
            'Repeat current frame',
            self.main_window,
        )
        toolbar.addAction(self.repeat_frame_action)

    def _create_video_fix_controls(self, toolbar: QToolBar):
        """Create video repair/transform toolbar controls."""
        self.fix_frame_count_btn = self._create_styled_button(
            'N*4+1',
            'Fix N*4+1 for selected videos',
            50,
            '#FF9800',
        )
        toolbar.addWidget(self.fix_frame_count_btn)

        self.fix_all_folder_btn = self._create_styled_button(
            'ALL',
            'Fix N*4+1 for all videos in folder',
            40,
            '#FF9800',
        )
        toolbar.addWidget(self.fix_all_folder_btn)

        self.fix_sar_btn = self._create_styled_button(
            'SAR',
            'Fix non-square pixels (SAR) for selected videos',
            40,
            '#FF5722',
        )
        toolbar.addWidget(self.fix_sar_btn)

        self.fix_all_sar_btn = self._create_styled_button(
            'SAR*',
            'Fix SAR for all videos in folder',
            45,
            '#FF5722',
        )
        toolbar.addWidget(self.fix_all_sar_btn)

        self.apply_speed_btn = self._create_styled_button(
            'SPEED',
            'Apply speed change to video (uses current speed slider value)',
            55,
            '#2196F3',
        )
        toolbar.addWidget(self.apply_speed_btn)

        self.change_fps_btn = self._create_styled_button(
            'FPS',
            'Change video FPS (drops/duplicates frames, preserves duration)\n'
            'Note: This can also be achieved with SPEED button at 1.0x + FPS override',
            40,
            '#03A9F4',
        )
        toolbar.addWidget(self.change_fps_btn)

    def _create_styled_button(self, text, tooltip, width, hover_color):
        """Create a styled button for video operations."""
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setMaximumWidth(width)
        button.setMaximumHeight(32)
        button.setStyleSheet(f"""
            QPushButton {{
                font-size: 11px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2b2b2b;
                padding: 4px;
                color: #ccc;
            }}
            QPushButton:hover {{
                border-color: {hover_color};
                background-color: #353535;
                color: {hover_color};
            }}
        """)
        return button

    def _create_rating_stars(self, toolbar: QToolBar):
        """Create rating and reaction widgets."""
        spring = QWidget()
        spring.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spring)

        self.reaction_controls_host_toggle_action = QAction('⋮', self.main_window)
        self.reaction_controls_host_toggle_action.setCheckable(True)
        self.reaction_controls_host_toggle_action.setToolTip(
            'Attach reactions to the main viewer overlay'
        )

        self.rating = 0
        self.reaction_controls_widget = ReactionControlsWidget(
            self,
            overlay_mode=False,
            parent=self.main_window,
        )
        self.rating_widget = self.reaction_controls_widget.rating_widget
        self.love_button = self.reaction_controls_widget.love_button
        self.bomb_button = self.reaction_controls_widget.bomb_button

        for i in range(6):
            shortcut = QShortcut(QKeySequence(f'Ctrl+{i}'), self.main_window)
            shortcut.activated.connect(
                lambda checked=False, rating=i: self.main_window.set_rating(rating / 5.0, True)
            )

        toolbar.addWidget(self.reaction_controls_widget)

    def _create_delete_marked_button(self):
        """Create delete marked images dropdown button."""
        self.delete_marked_btn = QPushButton('🗑️ Delete Marked ▼')
        self.delete_marked_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: white;
                border: 2px solid #b71c1c;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
                border-color: #c62828;
            }
            QPushButton:pressed {
                background-color: #b71c1c;
            }
            QPushButton::menu-indicator {
                width: 0px;
            }
        """)
        self.delete_marked_btn.setVisible(False)

        self.delete_marked_menu = QMenu(self.main_window)
        delete_all_action = QAction('Delete All Marked Images', self.main_window)
        delete_all_action.triggered.connect(self._delete_all_marked)
        self.delete_marked_menu.addAction(delete_all_action)

        unmark_all_action = QAction('Unmark All Images', self.main_window)
        unmark_all_action.triggered.connect(self._unmark_all_images)
        self.delete_marked_menu.addAction(unmark_all_action)

        self.delete_marked_btn.setMenu(self.delete_marked_menu)
        rating_toolbar = self.toolbars.get('rating')
        if rating_toolbar is not None:
            rating_toolbar.addWidget(self.delete_marked_btn)

    def set_zoom_follow_mode_button(self, mode: str):
        """Update compact zoom-follow button icon and tooltip."""
        if self.zoom_follow_mode_action is None:
            return
        normalized = str(mode or 'default').strip().lower()
        if normalized == 'fit_lock':
            icon = '⤢'
            tip = 'Fit Lock: Keep image fitted across image changes'
        elif normalized == 'scale_lock':
            icon = '🔒'
            tip = 'Zoom Lock: Keep same zoom detail across image changes'
        else:
            icon = '⛶'
            tip = 'Default: Per-image zoom behavior'
        self.zoom_follow_mode_action.setText(icon)
        self.zoom_follow_mode_action.setToolTip(tip)

    def set_main_viewer_controls_attached(self, attached: bool):
        """Update attach/detach label for the shared controls cluster."""
        if self.main_viewer_controls_host_toggle_action is None:
            return
        self.main_viewer_controls_host_toggle_action.setText('⋮')
        self.main_viewer_controls_host_toggle_action.setChecked(bool(attached))
        if attached:
            self.main_viewer_controls_host_toggle_action.setToolTip(
                'Return controls to the toolbar'
            )
        else:
            self.main_viewer_controls_host_toggle_action.setToolTip(
                'Attach controls to the main viewer overlay'
            )

    def set_reaction_controls_attached(self, attached: bool):
        """Update attach/detach label for the shared reaction cluster."""
        if self.reaction_controls_host_toggle_action is None:
            return
        self.reaction_controls_host_toggle_action.setText('⋮')
        self.reaction_controls_host_toggle_action.setChecked(bool(attached))
        if attached:
            self.reaction_controls_host_toggle_action.setToolTip(
                'Return reactions to the toolbar'
            )
        else:
            self.reaction_controls_host_toggle_action.setToolTip(
                'Attach reactions to the main viewer overlay'
            )

    def set_main_viewer_fullscreen_state(self, fullscreen: bool):
        """Update the shared main-viewer fullscreen action icon and tooltip."""
        if self.main_viewer_fullscreen_action is None:
            return
        fullscreen = bool(fullscreen)
        self.main_viewer_fullscreen_action.setChecked(fullscreen)
        if fullscreen:
            self.main_viewer_fullscreen_action.setIcon(create_fullscreen_icon(exit_fullscreen=True))
            self.main_viewer_fullscreen_action.setText('Exit Fullscreen')
            self.main_viewer_fullscreen_action.setToolTip('Exit Fullscreen (F, Esc)')
        else:
            self.main_viewer_fullscreen_action.setIcon(create_fullscreen_icon(exit_fullscreen=False))
            self.main_viewer_fullscreen_action.setText('Fullscreen')
            self.main_viewer_fullscreen_action.setToolTip('Fullscreen (F)')

    def create_main_viewer_controls_widget(self, *, overlay_mode: bool, parent=None):
        """Create one host widget for the shared main-viewer controls."""
        return MainViewerControlsWidget(self, overlay_mode=overlay_mode, parent=parent)

    def create_reaction_controls_widget(self, *, overlay_mode: bool, parent=None):
        """Create one host widget for the shared reaction controls."""
        return ReactionControlsWidget(self, overlay_mode=overlay_mode, parent=parent)

    def _delete_all_marked(self):
        """Delete all marked images."""
        if hasattr(self.main_window, 'image_list'):
            self.main_window.image_list.delete_marked_images()

    def _unmark_all_images(self):
        """Unmark all images marked for deletion."""
        if hasattr(self.main_window, 'image_list'):
            self.main_window.image_list.unmark_all_images()
