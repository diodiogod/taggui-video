"""Manager for main window toolbar setup."""

from PySide6.QtWidgets import (QToolBar, QPushButton, QWidget, QHBoxLayout,
                               QLabel, QSpinBox, QSizePolicy)
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut
from PySide6.QtCore import Qt

from utils.icons import (create_add_box_icon, toggle_marking_icon,
                         show_markings_icon, show_labels_icon,
                         show_marking_latent_icon)
from utils.settings import settings


class ToolbarManager:
    """Manages toolbar creation and setup."""

    def __init__(self, main_window):
        """Initialize toolbar manager."""
        self.main_window = main_window
        self.toolbar = None
        self.zoom_fit_best_action = None
        self.zoom_in_action = None
        self.zoom_original_action = None
        self.zoom_out_action = None
        self.add_action_group = None
        self.add_crop_action = None
        self.add_hint_action = None
        self.add_exclude_action = None
        self.add_include_action = None
        self.delete_marking_action = None
        self.add_toggle_marking_action = None
        self.add_show_marking_action = None
        self.add_show_labels_action = None
        self.add_show_marking_latent_action = None
        self.always_show_controls_btn = None
        self.fixed_marker_size_spinbox = None
        self.extract_range_action = None
        self.remove_range_action = None
        self.remove_frame_action = None
        self.repeat_frame_action = None
        self.fix_frame_count_btn = None
        self.fix_all_folder_btn = None
        self.fix_sar_btn = None
        self.fix_all_sar_btn = None
        self.star_labels = []
        self.rating = 0

    def create_toolbar(self):
        """Create and setup the main toolbar."""
        self.toolbar = QToolBar('Main toolbar', self.main_window)
        self.toolbar.setObjectName('Main toolbar')
        self.toolbar.setFloatable(True)
        self.main_window.addToolBar(self.toolbar)

        # Zoom controls
        self._create_zoom_controls()

        # Marking controls
        self.toolbar.addSeparator()
        self._create_marking_controls()

        # Video editing controls
        self.toolbar.addSeparator()
        self._create_video_controls()

        # Rating stars
        self._create_rating_stars()

        return self.toolbar

    def _create_zoom_controls(self):
        """Create zoom toolbar actions."""
        self.zoom_fit_best_action = QAction(QIcon.fromTheme('zoom-fit-best'),
                                            'Zoom to fit', self.main_window)
        self.zoom_fit_best_action.setCheckable(True)
        self.toolbar.addAction(self.zoom_fit_best_action)

        self.zoom_in_action = QAction(QIcon.fromTheme('zoom-in'),
                                      'Zoom in', self.main_window)
        self.toolbar.addAction(self.zoom_in_action)

        self.zoom_original_action = QAction(QIcon.fromTheme('zoom-original'),
                                            'Original size', self.main_window)
        self.zoom_original_action.setCheckable(True)
        self.toolbar.addAction(self.zoom_original_action)

        self.zoom_out_action = QAction(QIcon.fromTheme('zoom-out'),
                                       'Zoom out', self.main_window)
        self.toolbar.addAction(self.zoom_out_action)

    def _create_marking_controls(self):
        """Create marking toolbar actions."""
        self.add_action_group = QActionGroup(self.main_window)
        self.add_action_group.setExclusionPolicy(QActionGroup.ExclusiveOptional)

        self.add_crop_action = QAction(create_add_box_icon(Qt.blue),
                                       'Add crop', self.add_action_group)
        self.add_crop_action.setCheckable(True)
        self.toolbar.addAction(self.add_crop_action)

        self.add_hint_action = QAction(create_add_box_icon(Qt.gray),
                                       'Add hint', self.add_action_group)
        self.add_hint_action.setCheckable(True)
        self.toolbar.addAction(self.add_hint_action)

        self.add_exclude_action = QAction(create_add_box_icon(Qt.red),
                                          'Add exclude mask', self.add_action_group)
        self.add_exclude_action.setCheckable(True)
        self.toolbar.addAction(self.add_exclude_action)

        self.add_include_action = QAction(create_add_box_icon(Qt.green),
                                          'Add include mask', self.add_action_group)
        self.add_include_action.setCheckable(True)
        self.toolbar.addAction(self.add_include_action)

        self.delete_marking_action = QAction(QIcon.fromTheme('edit-delete'),
                                            'Delete marking', self.main_window)
        self.delete_marking_action.setEnabled(False)
        self.toolbar.addAction(self.delete_marking_action)

        self.add_toggle_marking_action = QAction(toggle_marking_icon(),
            'Change marking type', self.main_window)
        self.add_toggle_marking_action.setEnabled(False)
        self.toolbar.addAction(self.add_toggle_marking_action)

        self.add_show_marking_action = QAction(show_markings_icon(),
            'Show markings', self.main_window)
        self.add_show_marking_action.setCheckable(True)
        self.add_show_marking_action.setChecked(True)
        self.toolbar.addAction(self.add_show_marking_action)

        self.add_show_labels_action = QAction(show_labels_icon(),
            'Show labels', self.main_window)
        self.add_show_labels_action.setCheckable(True)
        self.add_show_labels_action.setChecked(True)
        self.toolbar.addAction(self.add_show_labels_action)

        self.add_show_marking_latent_action = QAction(show_marking_latent_icon(),
            'Show marking in latent space', self.main_window)
        self.add_show_marking_latent_action.setCheckable(True)
        self.add_show_marking_latent_action.setChecked(True)
        self.toolbar.addAction(self.add_show_marking_latent_action)

    def _create_video_controls(self):
        """Create video editing toolbar controls."""
        # Always show player controls toggle
        self.always_show_controls_btn = QPushButton('👁')
        self.always_show_controls_btn.setCheckable(True)
        self.always_show_controls_btn.setToolTip('Always show video controls')
        self.always_show_controls_btn.setMaximumWidth(32)
        self.always_show_controls_btn.setMaximumHeight(32)
        always_show = settings.value('video_always_show_controls', False, type=bool)
        self.always_show_controls_btn.setChecked(always_show)
        self.always_show_controls_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2b2b2b;
                padding: 4px;
            }
            QPushButton:hover {
                border-color: #777;
                background-color: #353535;
            }
            QPushButton:checked {
                border-color: #4CAF50;
                background-color: #2d5a2d;
                box-shadow: 0 0 8px #4CAF50;
            }
        """)
        self.toolbar.addWidget(self.always_show_controls_btn)

        # Fixed marker size spinbox
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
        self.fixed_marker_size_spinbox.setToolTip('Fixed frame count for auto markers (0 = Custom allows manual marker setting)')
        marker_size_layout.addWidget(marker_size_label)
        marker_size_layout.addWidget(self.fixed_marker_size_spinbox)
        self.toolbar.addWidget(marker_size_widget)

        # Video edit buttons
        self.extract_range_action = QAction(QIcon.fromTheme('document-save'),
            'Extract range to new video', self.main_window)
        self.toolbar.addAction(self.extract_range_action)

        self.remove_range_action = QAction(QIcon.fromTheme('edit-cut'),
            'Remove range from video', self.main_window)
        self.toolbar.addAction(self.remove_range_action)

        self.remove_frame_action = QAction(QIcon.fromTheme('edit-delete'),
            'Remove current frame', self.main_window)
        self.toolbar.addAction(self.remove_frame_action)

        self.repeat_frame_action = QAction(QIcon.fromTheme('edit-copy'),
            'Repeat current frame', self.main_window)
        self.toolbar.addAction(self.repeat_frame_action)

        # Fix frame count buttons
        self.fix_frame_count_btn = self._create_styled_button(
            'N*4+1', 'Fix N*4+1 for selected videos', 50, '#FF9800'
        )
        self.toolbar.addWidget(self.fix_frame_count_btn)

        self.fix_all_folder_btn = self._create_styled_button(
            'ALL', 'Fix N*4+1 for all videos in folder', 40, '#FF9800'
        )
        self.toolbar.addWidget(self.fix_all_folder_btn)

        # SAR fix buttons
        self.fix_sar_btn = self._create_styled_button(
            'SAR', 'Fix non-square pixels (SAR) for selected videos', 40, '#FF5722'
        )
        self.toolbar.addWidget(self.fix_sar_btn)

        self.fix_all_sar_btn = self._create_styled_button(
            'SAR*', 'Fix SAR for all videos in folder', 45, '#FF5722'
        )
        self.toolbar.addWidget(self.fix_all_sar_btn)

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

    def _create_rating_stars(self):
        """Create rating stars widget."""
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        star_widget = QWidget()
        star_layout = QHBoxLayout(star_widget)
        star_layout.setContentsMargins(0, 0, 0, 0)
        star_layout.setSpacing(0)

        self.rating = 0
        self.star_labels = []

        for i in range(6):
            shortcut = QShortcut(QKeySequence(f'Ctrl+{i}'), self.main_window)
            shortcut.activated.connect(lambda checked=False, rating=i:
                                       self.main_window.set_rating(2*rating, False))
            if i == 0:
                continue
            star_label = QLabel('☆', self.main_window)
            star_label.setEnabled(False)
            star_label.setAlignment(Qt.AlignCenter)
            star_label.setStyleSheet('QLabel { font-size: 22px; }')
            star_label.setToolTip(f'Ctrl+{i}')
            star_label.mousePressEvent = lambda event, rating=i: (
                self.main_window.set_rating(rating/5.0, True, event))
            self.star_labels.append(star_label)
            star_layout.addWidget(star_label)

        self.toolbar.addWidget(star_widget)
