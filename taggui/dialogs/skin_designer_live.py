"""Live player skin designer (v1): interact with real controls, not a mockup."""

from copy import deepcopy
from pathlib import Path
import re
import shutil
from datetime import datetime
import yaml

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QFontComboBox,
    QVBoxLayout,
    QWidget,
)

from widgets.video_controls import VideoControlsWidget


class AutoCloseColorDialog(QColorDialog):
    """Color dialog that auto-accepts on mouse release after interaction."""

    def __init__(self, initial: QColor, parent=None, title: str = "Pick Color"):
        super().__init__(initial, parent)
        self.setWindowTitle(title)
        self.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        self.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        self._armed_widget = None

    def showEvent(self, event):
        super().showEvent(event)
        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        self._armed_widget = None

    def closeEvent(self, event):
        self.removeEventFilter(self)
        for child in self.findChildren(QWidget):
            child.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(watched, QWidget) and self._is_main_color_area(watched):
                self._armed_widget = watched
            else:
                self._armed_widget = None
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._armed_widget is not None and isinstance(watched, QWidget):
                if watched is self._armed_widget or self._armed_widget.isAncestorOf(watched):
                    self._armed_widget = None
                    QTimer.singleShot(0, self.accept)
                    return True
            self._armed_widget = None
        return super().eventFilter(watched, event)

    def _is_main_color_area(self, widget: QWidget) -> bool:
        """Detect large sat/value rainbow area; avoid auto-close on sliders/spin boxes."""
        cls = widget.metaObject().className().lower() if widget.metaObject() else ""
        name = widget.objectName().lower() if widget.objectName() else ""
        if "slider" in cls or "spinbox" in cls or "lineedit" in cls:
            return False
        if "luminance" in cls or "luminance" in name:
            return False
        if "slider" in name or "spin" in name or "line" in name:
            return False
        if cls in ("qcolorpicker", "qcolorpicker"):
            return True
        if "colorpicker" in cls and "luminance" not in cls:
            return True
        if name in ("qt_colorpicker", "colorpicker"):
            return True
        return False


class SkinDesignerLive(QDialog):
    """Simple live skin designer bound to the real player widget structure."""

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle("Live Skin Designer (Simple)")
        self.resize(1200, 520)
        self.setStyleSheet("QToolTip { font-size: 11px; padding: 6px; }")

        self.video_controls = video_controls
        self._current_skin_path = None
        if video_controls and video_controls.skin_manager.current_skin:
            self.skin_data = deepcopy(video_controls.skin_manager.current_skin)
            self._current_skin_path = getattr(video_controls.skin_manager, "current_skin_path", None)
        else:
            self.skin_data = self._default_skin_data()
        self._normalize_for_designer_visibility()

        self._selected_component = None
        self._sync_pending = False
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(350)
        self._autosave_timer.timeout.connect(self._autosave_current_skin_quiet)

        root = QHBoxLayout(self)

        # Left: real player instance for click-select
        left = QVBoxLayout()
        left.addWidget(QLabel("Live Player (click any element)"))
        self.live_preview = VideoControlsWidget(self)
        self.live_preview.setMinimumHeight(180)
        # Keep timeline visibly filled while designing colors/styles.
        self.live_preview.timeline_slider.setMinimum(0)
        self.live_preview.timeline_slider.setMaximum(100)
        self.live_preview.timeline_slider.setValue(40)
        self.live_preview.show()
        left.addWidget(self.live_preview)
        root.addLayout(left, 2)

        # Selection outline overlay
        self.selection_frame = QFrame(self.live_preview)
        self.selection_frame.setStyleSheet("QFrame { border: 2px dashed #FFD54F; background: transparent; }")
        self.selection_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.selection_frame.hide()

        self._loading_global = False

        # Right: controls
        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(6)

        self.tabs = QTabWidget(panel)
        panel_layout.addWidget(self.tabs, 1)
        self._build_selection_tab()
        self._build_layout_tab()
        self._build_style_tab()
        self._build_scaling_tab()

        reset_layout_btn = QPushButton("Reset Layout")
        reset_layout_btn.clicked.connect(self._reset_layout)
        panel_layout.addWidget(reset_layout_btn)

        normalize_btn = QPushButton("Normalize Visible View")
        normalize_btn.clicked.connect(self._normalize_and_apply)
        panel_layout.addWidget(normalize_btn)

        self.save_as_btn = QPushButton("Save Skin As...")
        self.save_as_btn.clicked.connect(self._save_skin_yaml)
        panel_layout.addWidget(self.save_as_btn)

        self.reset_all_btn = QPushButton("Restore Defaults...")
        self.reset_all_btn.clicked.connect(self._restore_defaults_dialog)
        panel_layout.addWidget(self.reset_all_btn)

        self._set_help_tooltips()

        root.addWidget(panel, 1)

        self._component_widgets = self._build_component_map()
        self._install_click_handlers()
        self._load_global_controls()
        self._refresh_color_button_swatches()
        self._apply_skin_everywhere()

    def _set_help_tooltips(self):
        """Attach informative tooltips for all interactive designer fields."""
        tips = {
            # Selection tab
            self.size_spin: (
                "Size of the thing you selected.\n"
                "Example:\n"
                "- If you selected a button (Play/Stop/etc), this changes button size.\n"
                "- If you selected text, this changes text size.\n"
                "- If you selected Timeline, this changes timeline thickness.\n"
                "Think of this as BASE SIZE."
            ),
            self.component_align_combo: (
                "Where the selected item sits in its own area:\n"
                "- left: stick to left side\n"
                "- center: stay in middle\n"
                "- right: stick to right side\n"
                "Then Offset X/Y moves it from that base position."
            ),
            self.color_btn: (
                "Main color for the selected item.\n"
                "Examples:\n"
                "- Play button selected -> button background color\n"
                "- Time text selected -> text color\n"
                "- Timeline selected -> filled timeline color"
            ),
            self.opacity_slider: (
                "Transparency for selected item.\n"
                "100 = fully visible, 0 = invisible.\n"
                "If 'control_bar' is selected, this controls full bar background opacity."
            ),
            self.component_scale_spin: (
                "Scale of selected item.\n"
                "100% = normal. 150% = bigger. 50% = smaller.\n"
                "Think of this as MULTIPLIER on top of Size.\n"
                "Final size ~= Size x Scale."
            ),
            self.offset_x_spin: (
                "Move selected item left/right.\n"
                "Positive = move right.\n"
                "Negative = move left.\n"
                "Example: +20 moves it 20 pixels right."
            ),
            self.offset_y_spin: (
                "Move selected item up/down.\n"
                "Positive = move down.\n"
                "Negative = move up.\n"
                "Example: -100 moves it up to float above the bar."
            ),
            self.container_w_spin: (
                "Width of the selected item's layout area.\n"
                "0 = auto width.\n"
                "Useful for speed slider: larger width gives it more room.\n"
                "If Align is right, making width larger makes it grow to the left."
            ),
            self.container_h_spin: (
                "Height of the selected item's layout area.\n"
                "0 = auto height."
            ),
            self.button_shape_combo: (
                "Shape style for selected button.\n"
                "rounded/square/circle/star.\n"
                "Note: star is a visual style hint, not a true polygon clip."
            ),
            self.button_radius_spin: (
                "Corner roundness for selected button.\n"
                "Higher value = rounder corners."
            ),
            self.font_family_combo: (
                "Font family for selected text element.\n"
                "Works for labels and text-like controls."
            ),
            self.font_style_combo: (
                "Font style for selected text element.\n"
                "normal / bold / italic / bold+italic."
            ),
            # Layout tab
            self.alignment_combo: (
                "Global alignment for the TOP row group (Play/Stop/etc row).\n"
                "This moves the whole top row pack left/center/right."
            ),
            self.timeline_pos_combo: (
                "Where timeline row appears:\n"
                "- Above: top controls, then timeline, then bottom info\n"
                "- Below: top controls, then bottom info, then timeline"
            ),
            self.control_height_spin: (
                "Minimum height of the whole player control bar.\n"
                "If controls look cramped/squished, increase this."
            ),
            self.button_spacing_spin: (
                "Space between items in a row.\n"
                "Higher = more gap between buttons/labels/sliders."
            ),
            self.section_spacing_spin: (
                "Gap between bigger groups/sections.\n"
                "Use this when rows feel too dense."
            ),
            self.controls_x_spin: (
                "Move the entire TOP row horizontally.\n"
                "Top row = Play/Stop/Mute, frame controls, speed controls."
            ),
            self.controls_y_spin: (
                "Move the entire TOP row vertically.\n"
                "Useful to lift or lower all top-row controls at once."
            ),
            self.timeline_x_spin: (
                "Move the entire TIMELINE row left/right.\n"
                "Timeline row = seek bar with loop markers."
            ),
            self.timeline_y_spin: (
                "Move the entire TIMELINE row up/down.\n"
                "Example: move timeline closer to top controls."
            ),
            self.info_x_spin: (
                "Move the entire BOTTOM INFO row left/right.\n"
                "Info row = time text, fps, frame count, loop controls."
            ),
            self.info_y_spin: (
                "Move the entire BOTTOM INFO row up/down.\n"
                "Use this to tighten or loosen spacing with timeline."
            ),
            self.floating_bleed_spin: (
                "Extra empty transparent space around the player bar.\n"
                "Increase this if you want buttons to float outside the black bar\n"
                "without being visually cramped."
            ),
            # Style tab
            self.global_button_size_spin: (
                "Default button size for all buttons.\n"
                "You can still override per-button size in Selection tab."
            ),
            self.timeline_height_spin: "Default thickness of timeline bar.",
            self.handle_size_spin: "Default size of slider handle (the draggable knob).",
            self.global_label_font_spin: "Default text size for labels.",
            self.global_control_opacity: "Opacity of player background bar.",
            self.control_radius_spin: "Roundness of player background corners.",
            self.control_bar_color_btn: "Background color of the player bar.",
            self.button_bg_color_btn: "Default button background color.",
            self.button_hover_color_btn: "Default color when mouse hovers a button.",
            self.timeline_color_btn: "Filled part color of timeline.",
            self.timeline_bg_btn: "Empty/background part color of timeline.",
            self.text_color_btn: "Main text color (labels/time/etc).",
            self.text_secondary_btn: "Secondary text color (less important labels).",
            self.speed_start_btn: "Speed slider gradient start color.",
            self.speed_mid_btn: "Speed slider gradient middle color.",
            self.speed_end_btn: "Speed slider gradient end color.",
            self.loop_start_btn: "Color of loop-start marker.",
            self.loop_end_btn: "Color of loop-end marker.",
            self.marker_width_spin: (
                "Loop marker width in pixels.\n"
                "Higher value makes markers wider."
            ),
            self.marker_height_spin: (
                "Loop marker height in pixels.\n"
                "Higher value makes markers taller."
            ),
            self.marker_offset_y_spin: (
                "Vertical marker offset.\n"
                "Negative moves markers upward, positive downward."
            ),
            self.marker_outline_spin: "Thickness of marker outline.",
            self.marker_shape_combo: (
                "Marker shape style.\n"
                "triangle = classic pointer, diamond = diamond marker."
            ),
            # Scaling tab
            self.scale_ideal_spin: (
                "Reference width for auto-scaling.\n"
                "At this width, controls appear at normal scale."
            ),
            self.scale_min_spin: (
                "Smallest allowed auto-scale.\n"
                "Prevents controls becoming too tiny on narrow windows."
            ),
            self.scale_max_spin: (
                "Largest allowed auto-scale.\n"
                "Prevents controls becoming too huge on wide windows."
            ),
            self.save_as_btn: (
                "Save this skin as a new file.\n"
                "Use this to create variants without replacing current skin."
            ),
            self.reset_all_btn: (
                "Restore defaults dialog.\n"
                "You can restore only the current skin or all skins.\n"
                "A backup folder is created first."
            ),
        }
        for widget, text in tips.items():
            widget.setToolTip(text)

    def _scroll_tab(self, content: QWidget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_selection_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Selected Component (live click)"))
        self.selected_label = QLabel("None")
        self.selected_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.selected_label)

        grid = QGridLayout()
        layout.addLayout(grid)

        grid.addWidget(QLabel("Size"), 0, 0)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 120)
        self.size_spin.valueChanged.connect(self._on_size_changed)
        grid.addWidget(self.size_spin, 0, 1)

        grid.addWidget(QLabel("Align"), 1, 0)
        self.component_align_combo = QComboBox()
        self.component_align_combo.addItems(["left", "center", "right"])
        self.component_align_combo.currentTextChanged.connect(self._on_component_layout_changed)
        grid.addWidget(self.component_align_combo, 1, 1)

        self.color_btn = QPushButton("Pick Color")
        self.color_btn.clicked.connect(self._on_pick_color)
        grid.addWidget(self.color_btn, 2, 0, 1, 2)

        grid.addWidget(QLabel("Opacity"), 3, 0)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        grid.addWidget(self.opacity_slider, 3, 1)

        grid.addWidget(QLabel("Scale %"), 4, 0)
        self.component_scale_spin = QSpinBox()
        self.component_scale_spin.setRange(25, 400)
        self.component_scale_spin.valueChanged.connect(self._on_component_layout_changed)
        grid.addWidget(self.component_scale_spin, 4, 1)

        grid.addWidget(QLabel("Offset X"), 5, 0)
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-200, 200)
        self.offset_x_spin.valueChanged.connect(self._on_offset_changed)
        grid.addWidget(self.offset_x_spin, 5, 1)

        grid.addWidget(QLabel("Offset Y"), 6, 0)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-100, 100)
        self.offset_y_spin.valueChanged.connect(self._on_offset_changed)
        grid.addWidget(self.offset_y_spin, 6, 1)

        grid.addWidget(QLabel("Container W"), 7, 0)
        self.container_w_spin = QSpinBox()
        self.container_w_spin.setRange(0, 900)
        self.container_w_spin.valueChanged.connect(self._on_component_layout_changed)
        grid.addWidget(self.container_w_spin, 7, 1)

        grid.addWidget(QLabel("Container H"), 8, 0)
        self.container_h_spin = QSpinBox()
        self.container_h_spin.setRange(0, 300)
        self.container_h_spin.valueChanged.connect(self._on_component_layout_changed)
        grid.addWidget(self.container_h_spin, 8, 1)

        grid.addWidget(QLabel("Button Shape"), 9, 0)
        self.button_shape_combo = QComboBox()
        self.button_shape_combo.addItems(["rounded", "square", "circle", "star"])
        self.button_shape_combo.currentTextChanged.connect(self._on_button_shape_changed)
        grid.addWidget(self.button_shape_combo, 9, 1)

        grid.addWidget(QLabel("Button Radius"), 10, 0)
        self.button_radius_spin = QSpinBox()
        self.button_radius_spin.setRange(0, 80)
        self.button_radius_spin.valueChanged.connect(self._on_button_shape_changed)
        grid.addWidget(self.button_radius_spin, 10, 1)

        grid.addWidget(QLabel("Font Family"), 11, 0)
        self.font_family_combo = QFontComboBox()
        self.font_family_combo.currentFontChanged.connect(self._on_font_style_changed)
        grid.addWidget(self.font_family_combo, 11, 1)

        grid.addWidget(QLabel("Font Style"), 12, 0)
        self.font_style_combo = QComboBox()
        self.font_style_combo.addItems(["normal", "bold", "italic", "bold_italic"])
        self.font_style_combo.currentTextChanged.connect(self._on_font_style_changed)
        grid.addWidget(self.font_style_combo, 12, 1)

        layout.addStretch(1)
        self.tabs.addTab(self._scroll_tab(tab), "Selection")

    def _build_layout_tab(self):
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setVerticalSpacing(6)
        r = 0
        grid.addWidget(QLabel("Alignment"), r, 0)
        self.alignment_combo = QComboBox()
        self.alignment_combo.addItems(["left", "center", "right"])
        self.alignment_combo.currentTextChanged.connect(self._on_global_changed)
        grid.addWidget(self.alignment_combo, r, 1)
        r += 1

        grid.addWidget(QLabel("Timeline Pos"), r, 0)
        self.timeline_pos_combo = QComboBox()
        self.timeline_pos_combo.addItems(["above", "below"])
        self.timeline_pos_combo.currentTextChanged.connect(self._on_global_changed)
        grid.addWidget(self.timeline_pos_combo, r, 1)
        r += 1

        grid.addWidget(QLabel("Control Height"), r, 0)
        self.control_height_spin = QSpinBox()
        self.control_height_spin.setRange(40, 200)
        self.control_height_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.control_height_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Button Spacing"), r, 0)
        self.button_spacing_spin = QSpinBox()
        self.button_spacing_spin.setRange(0, 40)
        self.button_spacing_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.button_spacing_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Section Spacing"), r, 0)
        self.section_spacing_spin = QSpinBox()
        self.section_spacing_spin.setRange(0, 80)
        self.section_spacing_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.section_spacing_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Controls X"), r, 0)
        self.controls_x_spin = QSpinBox()
        self.controls_x_spin.setRange(-500, 500)
        self.controls_x_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.controls_x_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Controls Y"), r, 0)
        self.controls_y_spin = QSpinBox()
        self.controls_y_spin.setRange(-200, 200)
        self.controls_y_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.controls_y_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Timeline X"), r, 0)
        self.timeline_x_spin = QSpinBox()
        self.timeline_x_spin.setRange(-500, 500)
        self.timeline_x_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.timeline_x_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Timeline Y"), r, 0)
        self.timeline_y_spin = QSpinBox()
        self.timeline_y_spin.setRange(-200, 200)
        self.timeline_y_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.timeline_y_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Info X"), r, 0)
        self.info_x_spin = QSpinBox()
        self.info_x_spin.setRange(-500, 500)
        self.info_x_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.info_x_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Info Y"), r, 0)
        self.info_y_spin = QSpinBox()
        self.info_y_spin.setRange(-200, 200)
        self.info_y_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.info_y_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Floating Bleed"), r, 0)
        self.floating_bleed_spin = QSpinBox()
        self.floating_bleed_spin.setRange(0, 200)
        self.floating_bleed_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.floating_bleed_spin, r, 1)
        self.tabs.addTab(self._scroll_tab(tab), "Layout")

    def _build_style_tab(self):
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setVerticalSpacing(6)
        r = 0
        grid.addWidget(QLabel("Global Button Size"), r, 0)
        self.global_button_size_spin = QSpinBox()
        self.global_button_size_spin.setRange(16, 120)
        self.global_button_size_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.global_button_size_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Timeline Height"), r, 0)
        self.timeline_height_spin = QSpinBox()
        self.timeline_height_spin.setRange(2, 40)
        self.timeline_height_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.timeline_height_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Handle Size"), r, 0)
        self.handle_size_spin = QSpinBox()
        self.handle_size_spin.setRange(6, 60)
        self.handle_size_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.handle_size_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Label Font Size"), r, 0)
        self.global_label_font_spin = QSpinBox()
        self.global_label_font_spin.setRange(8, 32)
        self.global_label_font_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.global_label_font_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Control Opacity"), r, 0)
        self.global_control_opacity = QSlider(Qt.Orientation.Horizontal)
        self.global_control_opacity.setRange(0, 100)
        self.global_control_opacity.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.global_control_opacity, r, 1)
        r += 1

        grid.addWidget(QLabel("Player Radius"), r, 0)
        self.control_radius_spin = QSpinBox()
        self.control_radius_spin.setRange(0, 80)
        self.control_radius_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.control_radius_spin, r, 1)
        r += 1

        self.control_bar_color_btn = self._add_color_button(grid, r, "Control Color", self._pick_control_bar_color); r += 1
        self.button_bg_color_btn = self._add_color_button(grid, r, "Button BG", self._pick_button_bg_color); r += 1
        self.button_hover_color_btn = self._add_color_button(grid, r, "Button Hover", self._pick_button_hover_color); r += 1
        self.timeline_color_btn = self._add_color_button(grid, r, "Timeline Color", self._pick_timeline_color); r += 1
        self.timeline_bg_btn = self._add_color_button(grid, r, "Timeline BG", self._pick_timeline_bg_color); r += 1
        self.text_color_btn = self._add_color_button(grid, r, "Text Color", self._pick_text_color); r += 1
        self.text_secondary_btn = self._add_color_button(grid, r, "Text Secondary", self._pick_text_secondary_color); r += 1
        self.speed_start_btn = self._add_color_button(grid, r, "Speed Grad Start", self._pick_speed_start_color); r += 1
        self.speed_mid_btn = self._add_color_button(grid, r, "Speed Grad Mid", self._pick_speed_mid_color); r += 1
        self.speed_end_btn = self._add_color_button(grid, r, "Speed Grad End", self._pick_speed_end_color); r += 1
        self.loop_start_btn = self._add_color_button(grid, r, "Loop Start", self._pick_loop_start_color); r += 1
        self.loop_end_btn = self._add_color_button(grid, r, "Loop End", self._pick_loop_end_color); r += 1

        grid.addWidget(QLabel("Marker Width"), r, 0)
        self.marker_width_spin = QSpinBox()
        self.marker_width_spin.setRange(8, 80)
        self.marker_width_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.marker_width_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Marker Height"), r, 0)
        self.marker_height_spin = QSpinBox()
        self.marker_height_spin.setRange(6, 80)
        self.marker_height_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.marker_height_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Marker Y Offset"), r, 0)
        self.marker_offset_y_spin = QSpinBox()
        self.marker_offset_y_spin.setRange(-60, 60)
        self.marker_offset_y_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.marker_offset_y_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Marker Outline"), r, 0)
        self.marker_outline_spin = QSpinBox()
        self.marker_outline_spin.setRange(1, 10)
        self.marker_outline_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.marker_outline_spin, r, 1)
        r += 1

        grid.addWidget(QLabel("Marker Shape"), r, 0)
        self.marker_shape_combo = QComboBox()
        self.marker_shape_combo.addItems(["triangle", "diamond"])
        self.marker_shape_combo.currentTextChanged.connect(self._on_global_changed)
        grid.addWidget(self.marker_shape_combo, r, 1)
        self.tabs.addTab(self._scroll_tab(tab), "Style")

    def _build_scaling_tab(self):
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Scale Ideal W"), 0, 0)
        self.scale_ideal_spin = QSpinBox()
        self.scale_ideal_spin.setRange(200, 2000)
        self.scale_ideal_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.scale_ideal_spin, 0, 1)

        grid.addWidget(QLabel("Scale Min %"), 1, 0)
        self.scale_min_spin = QSpinBox()
        self.scale_min_spin.setRange(10, 200)
        self.scale_min_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.scale_min_spin, 1, 1)

        grid.addWidget(QLabel("Scale Max %"), 2, 0)
        self.scale_max_spin = QSpinBox()
        self.scale_max_spin.setRange(10, 300)
        self.scale_max_spin.valueChanged.connect(self._on_global_changed)
        grid.addWidget(self.scale_max_spin, 2, 1)

        self.tabs.addTab(self._scroll_tab(tab), "Scaling")

    def _vp(self):
        return self.skin_data.setdefault("video_player", {})

    def _layout_cfg(self):
        return self._vp().setdefault("layout", {})

    def _styling_cfg(self):
        return self._vp().setdefault("styling", {})

    def _borders_cfg(self):
        return self._vp().setdefault("borders", {})

    def _designer_cfg(self):
        return self._vp().setdefault("designer_layout", {})

    def _controls_row_cfg(self):
        return self._designer_cfg().setdefault("controls_row", {})

    def _timeline_row_cfg(self):
        return self._designer_cfg().setdefault("timeline_row", {})

    def _info_row_cfg(self):
        return self._designer_cfg().setdefault("info_row", {})

    def _scaling_cfg(self):
        return self._designer_cfg().setdefault("scaling", {})

    def _component_layouts_cfg(self):
        return self._designer_cfg().setdefault("component_layouts", {})

    def _component_layout_cfg(self, component_id):
        return self._component_layouts_cfg().setdefault(component_id, {})

    def _add_color_button(self, grid, row, label, callback):
        grid.addWidget(QLabel(label), row, 0)
        btn = QPushButton("Pick")
        btn.clicked.connect(callback)
        grid.addWidget(btn, row, 1)
        return btn

    def _best_text_color(self, color_hex: str) -> str:
        c = QColor(color_hex)
        if not c.isValid():
            return "#FFFFFF"
        luminance = (0.299 * c.red()) + (0.587 * c.green()) + (0.114 * c.blue())
        return "#000000" if luminance > 170 else "#FFFFFF"

    def _style_color_button(self, button: QPushButton, color_hex: str, label: str):
        fg = self._best_text_color(color_hex)
        button.setText(label)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {color_hex}; color: {fg}; border: 1px solid #666; border-radius: 4px; padding: 2px 6px; }}"
        )

    def _refresh_color_button_swatches(self):
        styling = self._styling_cfg()
        pairs = [
            (self.control_bar_color_btn, "control_bar_color", "Control"),
            (self.button_bg_color_btn, "button_bg_color", "Button"),
            (self.button_hover_color_btn, "button_hover_color", "Hover"),
            (self.timeline_color_btn, "timeline_color", "Timeline"),
            (self.timeline_bg_btn, "timeline_bg_color", "Timeline BG"),
            (self.text_color_btn, "text_color", "Text"),
            (self.text_secondary_btn, "text_secondary_color", "Text 2"),
            (self.speed_start_btn, "speed_gradient_start", "Speed A"),
            (self.speed_mid_btn, "speed_gradient_mid", "Speed B"),
            (self.speed_end_btn, "speed_gradient_end", "Speed C"),
            (self.loop_start_btn, "loop_marker_start_color", "Loop Start"),
            (self.loop_end_btn, "loop_marker_end_color", "Loop End"),
        ]
        for button, key, label in pairs:
            color_hex = str(styling.get(key, "#888888"))
            self._style_color_button(button, color_hex, label)
        self._refresh_selected_color_button()

    def _selected_component_color(self) -> str:
        component_id = self._selected_component
        if not component_id:
            return "#FFFFFF"
        block = self._component_style_block(component_id)
        styling = self._styling_cfg()
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            return str(block.get("button_bg_color", styling.get("button_bg_color", "#2b2b2b")))
        if "label" in component_id:
            return str(block.get("text_color", styling.get("text_color", "#FFFFFF")))
        if component_id == "timeline_slider":
            return str(block.get("timeline_color", styling.get("timeline_color", "#2196F3")))
        if component_id == "speed_slider":
            return str(block.get("speed_gradient_mid", styling.get("speed_gradient_mid", "#6B8E23")))
        if component_id == "control_bar":
            return str(styling.get("control_bar_color", "#000000"))
        return "#FFFFFF"

    def _refresh_selected_color_button(self):
        color_hex = self._selected_component_color()
        self._style_color_button(self.color_btn, color_hex, "Pick Color")

    def _load_global_controls(self):
        self._loading_global = True
        layout = self._layout_cfg()
        styling = self._styling_cfg()
        borders = self._borders_cfg()
        borders = self._borders_cfg()
        controls = self._controls_row_cfg()
        timeline = self._timeline_row_cfg()
        info = self._info_row_cfg()
        scaling = self._scaling_cfg()

        self.alignment_combo.setCurrentText(str(layout.get("button_alignment", "center")))
        self.timeline_pos_combo.setCurrentText(str(layout.get("timeline_position", "above")))
        self.control_height_spin.setValue(int(layout.get("control_bar_height", 60)))
        self.button_spacing_spin.setValue(int(layout.get("button_spacing", 8)))
        self.section_spacing_spin.setValue(int(layout.get("section_spacing", 20)))
        self.global_button_size_spin.setValue(int(styling.get("button_size", 40)))
        self.timeline_height_spin.setValue(int(styling.get("timeline_height", 8)))
        self.handle_size_spin.setValue(int(styling.get("slider_handle_size", 16)))
        self.global_label_font_spin.setValue(int(styling.get("label_font_size", 12)))
        self.global_control_opacity.setValue(int(float(styling.get("control_bar_opacity", 0.8)) * 100))
        self.control_radius_spin.setValue(int(borders.get("radius", 6)))
        self.marker_width_spin.setValue(int(styling.get("loop_marker_width", 18)))
        self.marker_height_spin.setValue(int(styling.get("loop_marker_height", 14)))
        self.marker_offset_y_spin.setValue(int(styling.get("loop_marker_offset_y", -2)))
        self.marker_outline_spin.setValue(int(styling.get("loop_marker_outline_width", 2)))
        self.marker_shape_combo.setCurrentText(str(styling.get("loop_marker_shape", "triangle")))

        self.controls_x_spin.setValue(int(controls.get("offset_x", 0)))
        self.controls_y_spin.setValue(int(controls.get("offset_y", 0)))
        self.timeline_x_spin.setValue(int(timeline.get("offset_x", 0)))
        self.timeline_y_spin.setValue(int(timeline.get("offset_y", 0)))
        self.info_x_spin.setValue(int(info.get("offset_x", 0)))
        self.info_y_spin.setValue(int(info.get("offset_y", 0)))
        self.floating_bleed_spin.setValue(int(self._designer_cfg().get("floating_bleed", 0)))

        self.scale_ideal_spin.setValue(int(scaling.get("ideal_width", 800)))
        self.scale_min_spin.setValue(int(float(scaling.get("min_scale", 0.5)) * 100))
        self.scale_max_spin.setValue(int(float(scaling.get("max_scale", 1.0)) * 100))
        self._loading_global = False

    def _default_skin_data(self):
        return {
            "name": "Custom Skin",
            "version": "1.0",
            "video_player": {
                "layout": {
                    "control_bar_height": 60,
                    "button_alignment": "center",
                    "timeline_position": "above",
                    "button_spacing": 10,
                    "section_spacing": 20,
                },
                "styling": {
                    "control_bar_color": "#000000",
                    "control_bar_opacity": 0.8,
                    "button_size": 36,
                    "button_bg_color": "#2b2b2b",
                    "button_hover_color": "#3a3a3a",
                    "timeline_height": 8,
                    "timeline_color": "#2196F3",
                    "timeline_bg_color": "#1A1A1A",
                    "slider_handle_size": 16,
                    "speed_gradient_start": "#2D5A2D",
                    "speed_gradient_mid": "#6B8E23",
                    "speed_gradient_end": "#32CD32",
                    "loop_marker_start_color": "#FF0080",
                    "loop_marker_end_color": "#FF8C00",
                    "loop_marker_outline": "#FFFFFF",
                    "loop_marker_outline_width": 2,
                    "loop_marker_width": 18,
                    "loop_marker_height": 14,
                    "loop_marker_offset_y": -2,
                    "loop_marker_shape": "triangle",
                    "text_color": "#FFFFFF",
                    "text_secondary_color": "#B0B0B0",
                    "label_font_size": 12,
                },
                "borders": {
                    "radius": 6,
                },
                "designer_layout": {
                    "controls_row": {"offset_x": 0, "offset_y": 0},
                    "timeline_row": {"offset_x": 0, "offset_y": 0},
                    "info_row": {"offset_x": 0, "offset_y": 0},
                    "component_layouts": {},
                    "floating_bleed": 80,
                    "scaling": {"ideal_width": 800, "min_scale": 0.5, "max_scale": 1.0},
                },
            },
        }

    def _normalize_for_designer_visibility(self):
        """Clamp risky values so live preview remains visible/clickable."""
        styling = self._styling_cfg()
        borders = self._borders_cfg()
        layout = self._layout_cfg()
        controls = self._controls_row_cfg()
        timeline = self._timeline_row_cfg()
        info = self._info_row_cfg()
        scaling = self._scaling_cfg()

        styling["control_bar_opacity"] = max(0.35, min(1.0, float(styling.get("control_bar_opacity", 0.8))))
        styling["button_size"] = max(16, min(100, int(styling.get("button_size", 40))))
        styling["label_font_size"] = max(8, min(32, int(styling.get("label_font_size", 12))))
        styling["timeline_height"] = max(2, min(30, int(styling.get("timeline_height", 8))))
        styling["slider_handle_size"] = max(6, min(40, int(styling.get("slider_handle_size", 16))))
        styling["loop_marker_outline_width"] = max(1, min(10, int(styling.get("loop_marker_outline_width", 2))))
        styling["loop_marker_width"] = max(8, min(80, int(styling.get("loop_marker_width", 18))))
        styling["loop_marker_height"] = max(6, min(80, int(styling.get("loop_marker_height", 14))))
        styling["loop_marker_offset_y"] = max(-60, min(60, int(styling.get("loop_marker_offset_y", -2))))
        shape = str(styling.get("loop_marker_shape", "triangle")).lower()
        styling["loop_marker_shape"] = shape if shape in ("triangle", "diamond") else "triangle"
        borders["radius"] = max(0, min(80, int(borders.get("radius", 6))))

        layout["control_bar_height"] = max(40, min(180, int(layout.get("control_bar_height", 60))))
        layout["button_spacing"] = max(10, min(40, int(layout.get("button_spacing", 10))))
        layout["section_spacing"] = max(0, min(80, int(layout.get("section_spacing", 20))))
        if layout.get("button_alignment") not in ("left", "center", "right"):
            layout["button_alignment"] = "center"
        if layout.get("timeline_position") not in ("above", "below"):
            layout["timeline_position"] = "above"

        for row in (controls, timeline, info):
            row["offset_x"] = max(-180, min(180, int(row.get("offset_x", 0))))
            row["offset_y"] = max(-80, min(80, int(row.get("offset_y", 0))))
        designer = self._designer_cfg()
        designer["floating_bleed"] = max(0, min(200, int(designer.get("floating_bleed", 0))))

        component_layouts = self._component_layouts_cfg()
        for component_id, cfg in list(component_layouts.items()):
            if not isinstance(cfg, dict):
                component_layouts[component_id] = {}
                continue
            cfg["align"] = cfg.get("align", "center")
            if cfg["align"] not in ("left", "center", "right"):
                cfg["align"] = "center"
            cfg["offset_x"] = max(-200, min(200, int(cfg.get("offset_x", 0))))
            cfg["offset_y"] = max(-100, min(100, int(cfg.get("offset_y", 0))))
            cfg["scale"] = max(0.25, min(4.0, float(cfg.get("scale", 1.0))))
            cfg["container_width"] = max(0, min(900, int(cfg.get("container_width", 0))))
            cfg["container_height"] = max(0, min(300, int(cfg.get("container_height", 0))))

        scaling["ideal_width"] = max(300, min(2000, int(scaling.get("ideal_width", 800))))
        scaling["min_scale"] = max(0.2, min(2.0, float(scaling.get("min_scale", 0.5))))
        scaling["max_scale"] = max(float(scaling["min_scale"]), min(3.0, float(scaling.get("max_scale", 1.0))))

    def _build_component_map(self):
        c = self.live_preview
        return {
            "play_button": c.play_pause_btn,
            "stop_button": c.stop_btn,
            "mute_button": c.mute_btn,
            "skip_back_button": c.skip_back_btn,
            "prev_frame_button": c.prev_frame_btn,
            "next_frame_button": c.next_frame_btn,
            "skip_forward_button": c.skip_forward_btn,
            "frame_label": c.frame_label,
            "frame_spinbox": c.frame_spinbox,
            "frame_total_label": c.frame_total_label,
            "time_label": c.time_label,
            "fps_label": c.fps_label,
            "frame_count_label": c.frame_count_label,
            "speed_label": c.speed_label,
            "speed_value_label": c.speed_value_label,
            "timeline_slider": c.timeline_slider,
            "speed_slider": c.speed_slider,
            "loop_reset_button": c.loop_reset_btn,
            "loop_start_button": c.loop_start_btn,
            "loop_end_button": c.loop_end_btn,
            "loop_checkbox": c.loop_checkbox,
            "control_bar": c,
        }

    def _install_click_handlers(self):
        # Root-level catcher for clicks anywhere on the live preview.
        self.live_preview.installEventFilter(self)
        for component_id, widget in self._component_widgets.items():
            widget.setProperty("designer_component_id", component_id)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            # First try direct property on the watched widget.
            component_id = watched.property("designer_component_id")
            if component_id:
                self._select_component(component_id)
                return True

            # Fallback: resolve click target via ancestry inside live preview.
            if watched is self.live_preview:
                pos = event.position().toPoint()
                clicked = self.live_preview.childAt(pos)
                resolved = self._resolve_component_from_widget(clicked)
                if resolved:
                    self._select_component(resolved)
                    return True
        return super().eventFilter(watched, event)

    def _resolve_component_from_widget(self, widget):
        """Resolve selected component id from a clicked widget/ancestor."""
        current = widget
        while current is not None:
            component_id = current.property("designer_component_id")
            if component_id:
                return component_id
            current = current.parentWidget() if hasattr(current, "parentWidget") else None
        return None

    def _select_component(self, component_id):
        self._selected_component = component_id
        self.selected_label.setText(component_id)
        self._move_selection_frame(component_id)
        self._load_controls_for_selection()
        self._refresh_selected_color_button()

    def _move_selection_frame(self, component_id):
        widget = self._component_widgets.get(component_id)
        if not widget:
            self.selection_frame.hide()
            return
        top_left = widget.mapTo(self.live_preview, widget.rect().topLeft())
        self.selection_frame.setGeometry(top_left.x() - 2, top_left.y() - 2, widget.width() + 4, widget.height() + 4)
        self.selection_frame.show()
        self.selection_frame.raise_()

    def _component_styles(self):
        vp = self.skin_data.setdefault("video_player", {})
        return vp.setdefault("component_styles", {})

    def _component_style_block(self, component_id):
        styles = self._component_styles()
        block = styles.setdefault(component_id, {})
        return block.setdefault("default", {})

    def _designer_layout(self):
        vp = self.skin_data.setdefault("video_player", {})
        return vp.setdefault("designer_layout", {})

    def _row_key_for_component(self, component_id):
        top_row = {
            "play_button", "stop_button", "mute_button", "skip_back_button",
            "prev_frame_button", "next_frame_button", "skip_forward_button",
            "frame_label", "speed_label", "speed_value_label", "speed_slider",
        }
        if component_id in top_row:
            return "controls_row"
        if component_id == "timeline_slider":
            return "timeline_row"
        if component_id == "control_bar":
            return "controls_row"
        return "info_row"

    def _load_controls_for_selection(self):
        component_id = self._selected_component
        if not component_id:
            return
        block = self._component_style_block(component_id)
        layout_cfg = self._component_layout_cfg(component_id)

        # Size key by type
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            size = int(block.get("button_size", self.skin_data["video_player"]["styling"].get("button_size", 40)))
        elif "label" in component_id:
            size = int(block.get("label_font_size", self.skin_data["video_player"]["styling"].get("label_font_size", 12)))
        elif component_id == "timeline_slider":
            size = int(block.get("timeline_height", self.skin_data["video_player"]["styling"].get("timeline_height", 8)))
        elif component_id == "control_bar":
            size = int(self._layout_cfg().get("control_bar_height", 60))
        else:
            size = int(block.get("slider_handle_size", self.skin_data["video_player"]["styling"].get("slider_handle_size", 16)))
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(size)
        self.size_spin.blockSignals(False)

        opacity = float(block.get("opacity", 1.0))
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(max(0.0, min(1.0, opacity)) * 100))
        self.opacity_slider.blockSignals(False)

        self.component_align_combo.blockSignals(True)
        self.component_align_combo.setCurrentText(str(layout_cfg.get("align", "center")))
        self.component_align_combo.blockSignals(False)

        self.component_scale_spin.blockSignals(True)
        self.component_scale_spin.setValue(int(float(layout_cfg.get("scale", 1.0)) * 100))
        self.component_scale_spin.blockSignals(False)

        self.offset_x_spin.blockSignals(True)
        self.offset_y_spin.blockSignals(True)
        self.offset_x_spin.setValue(int(layout_cfg.get("offset_x", 0)))
        self.offset_y_spin.setValue(int(layout_cfg.get("offset_y", 0)))
        self.offset_x_spin.blockSignals(False)
        self.offset_y_spin.blockSignals(False)

        self.container_w_spin.blockSignals(True)
        self.container_h_spin.blockSignals(True)
        self.container_w_spin.setValue(int(layout_cfg.get("container_width", 0)))
        self.container_h_spin.setValue(int(layout_cfg.get("container_height", 0)))
        self.container_w_spin.blockSignals(False)
        self.container_h_spin.blockSignals(False)

        self.button_shape_combo.blockSignals(True)
        self.button_radius_spin.blockSignals(True)
        self.button_shape_combo.setCurrentText(str(block.get("button_shape", "rounded")))
        self.button_radius_spin.setValue(int(block.get("button_border_radius", self._styling_cfg().get("button_border_radius", 6))))
        self.button_shape_combo.blockSignals(False)
        self.button_radius_spin.blockSignals(False)

        self.font_family_combo.blockSignals(True)
        self.font_style_combo.blockSignals(True)
        if component_id == "loop_checkbox":
            family = str(block.get("button_font_family", "Arial"))
            style_name = str(block.get("button_font_style", "normal"))
        else:
            family = str(block.get("label_font_family", "Arial"))
            style_name = str(block.get("label_font_style", "normal"))
        self.font_family_combo.setCurrentFont(QFont(family))
        self.font_style_combo.setCurrentText(style_name)
        self.font_family_combo.blockSignals(False)
        self.font_style_combo.blockSignals(False)

        is_control_bar = component_id == "control_bar"
        is_button = component_id.endswith("_button") or component_id == "loop_checkbox"
        is_textual = ("label" in component_id) or component_id in ("loop_checkbox", "frame_spinbox")
        for widget in (
            self.component_align_combo,
            self.component_scale_spin,
            self.offset_x_spin,
            self.offset_y_spin,
            self.container_w_spin,
            self.container_h_spin,
        ):
            widget.setEnabled(not is_control_bar)
        self.button_shape_combo.setEnabled(is_button)
        self.button_radius_spin.setEnabled(is_button)
        self.font_family_combo.setEnabled(is_textual)
        self.font_style_combo.setEnabled(is_textual)

    def _on_size_changed(self, value):
        if not self._selected_component:
            return
        block = self._component_style_block(self._selected_component)
        component_id = self._selected_component
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            block["button_size"] = int(value)
        elif "label" in component_id:
            block["label_font_size"] = int(value)
        elif component_id == "timeline_slider":
            block["timeline_height"] = int(value)
        elif component_id == "control_bar":
            self._layout_cfg()["control_bar_height"] = int(value)
        else:
            block["slider_handle_size"] = int(value)
        self._apply_skin_everywhere()

    def _on_pick_color(self):
        if not self._selected_component:
            return
        def _live(c: QColor):
            if not c.isValid() or not self._selected_component:
                return
            block_live = self._component_style_block(self._selected_component)
            cid_live = self._selected_component
            if cid_live.endswith("_button") or cid_live == "loop_checkbox":
                block_live["button_bg_color"] = c.name()
            elif "label" in cid_live:
                block_live["text_color"] = c.name()
            elif cid_live == "timeline_slider":
                block_live["timeline_color"] = c.name()
            elif cid_live == "speed_slider":
                block_live["speed_gradient_mid"] = c.name()
            elif cid_live == "control_bar":
                self._styling_cfg()["control_bar_color"] = c.name()
            self._apply_skin_everywhere()

        color = self._pick_color_dialog(QColor(self._selected_component_color()), "Pick Color", on_live_change=_live)
        if not color.isValid():
            return
        block = self._component_style_block(self._selected_component)
        component_id = self._selected_component
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            block["button_bg_color"] = color.name()
        elif "label" in component_id:
            block["text_color"] = color.name()
        elif component_id == "timeline_slider":
            block["timeline_color"] = color.name()
        elif component_id == "speed_slider":
            block["speed_gradient_mid"] = color.name()
        elif component_id == "control_bar":
            self.skin_data["video_player"]["styling"]["control_bar_color"] = color.name()
        self._apply_skin_everywhere()
        self._refresh_selected_color_button()

    def _on_opacity_changed(self, value):
        if not self._selected_component:
            return
        opacity = max(0.0, min(1.0, value / 100.0))
        if self._selected_component == "control_bar":
            self.skin_data["video_player"]["styling"]["control_bar_opacity"] = opacity
        else:
            self._component_style_block(self._selected_component)["opacity"] = opacity
        self._apply_skin_everywhere()

    def _on_offset_changed(self):
        if not self._selected_component:
            return
        cfg = self._component_layout_cfg(self._selected_component)
        cfg["offset_x"] = int(self.offset_x_spin.value())
        cfg["offset_y"] = int(self.offset_y_spin.value())
        self._apply_skin_everywhere()

    def _on_component_layout_changed(self):
        if not self._selected_component:
            return
        cfg = self._component_layout_cfg(self._selected_component)
        cfg["align"] = self.component_align_combo.currentText()
        cfg["scale"] = float(self.component_scale_spin.value()) / 100.0
        cfg["container_width"] = int(self.container_w_spin.value())
        cfg["container_height"] = int(self.container_h_spin.value())
        self._apply_skin_everywhere()

    def _on_button_shape_changed(self):
        if not self._selected_component:
            return
        component_id = self._selected_component
        if not (component_id.endswith("_button") or component_id == "loop_checkbox"):
            return
        block = self._component_style_block(component_id)
        block["button_shape"] = self.button_shape_combo.currentText()
        block["button_border_radius"] = int(self.button_radius_spin.value())
        self._apply_skin_everywhere()

    def _on_font_style_changed(self):
        if not self._selected_component:
            return
        component_id = self._selected_component
        if not (("label" in component_id) or component_id in ("loop_checkbox", "frame_spinbox")):
            return
        block = self._component_style_block(component_id)
        if component_id == "loop_checkbox":
            block["button_font_family"] = self.font_family_combo.currentFont().family()
            block["button_font_style"] = self.font_style_combo.currentText()
        else:
            block["label_font_family"] = self.font_family_combo.currentFont().family()
            block["label_font_style"] = self.font_style_combo.currentText()
        self._apply_skin_everywhere()

    def _on_global_changed(self):
        if self._loading_global:
            return
        layout = self._layout_cfg()
        styling = self._styling_cfg()
        borders = self._borders_cfg()
        controls = self._controls_row_cfg()
        timeline = self._timeline_row_cfg()
        info = self._info_row_cfg()
        scaling = self._scaling_cfg()

        layout["button_alignment"] = self.alignment_combo.currentText()
        layout["timeline_position"] = self.timeline_pos_combo.currentText()
        layout["control_bar_height"] = int(self.control_height_spin.value())
        layout["button_spacing"] = int(self.button_spacing_spin.value())
        layout["section_spacing"] = int(self.section_spacing_spin.value())

        styling["button_size"] = int(self.global_button_size_spin.value())
        styling["timeline_height"] = int(self.timeline_height_spin.value())
        styling["slider_handle_size"] = int(self.handle_size_spin.value())
        styling["label_font_size"] = int(self.global_label_font_spin.value())
        styling["control_bar_opacity"] = float(self.global_control_opacity.value()) / 100.0
        borders["radius"] = int(self.control_radius_spin.value())
        styling["loop_marker_width"] = int(self.marker_width_spin.value())
        styling["loop_marker_height"] = int(self.marker_height_spin.value())
        styling["loop_marker_offset_y"] = int(self.marker_offset_y_spin.value())
        styling["loop_marker_outline_width"] = int(self.marker_outline_spin.value())
        styling["loop_marker_shape"] = self.marker_shape_combo.currentText()

        controls["offset_x"] = int(self.controls_x_spin.value())
        controls["offset_y"] = int(self.controls_y_spin.value())
        timeline["offset_x"] = int(self.timeline_x_spin.value())
        timeline["offset_y"] = int(self.timeline_y_spin.value())
        info["offset_x"] = int(self.info_x_spin.value())
        info["offset_y"] = int(self.info_y_spin.value())
        self._designer_cfg()["floating_bleed"] = int(self.floating_bleed_spin.value())

        scaling["ideal_width"] = int(self.scale_ideal_spin.value())
        scaling["min_scale"] = float(self.scale_min_spin.value()) / 100.0
        scaling["max_scale"] = float(self.scale_max_spin.value()) / 100.0
        self._apply_skin_everywhere()

    def _pick_color(self, key):
        current = self._styling_cfg().get(key, "#FFFFFF")
        def _live(c: QColor):
            if c.isValid():
                self._styling_cfg()[key] = c.name()
                self._apply_skin_everywhere()
        color = self._pick_color_dialog(QColor(current), f"Pick {key}", on_live_change=_live)
        if not color.isValid():
            return
        self._styling_cfg()[key] = color.name()
        self._apply_skin_everywhere()
        self._refresh_color_button_swatches()

    def _pick_color_dialog(self, initial: QColor, title: str, on_live_change=None) -> QColor:
        """Open auto-close color picker; release after selecting applies instantly."""
        dlg = AutoCloseColorDialog(initial, self, title)
        if on_live_change is not None:
            dlg.currentColorChanged.connect(on_live_change)
        dlg.exec()
        # Keep currently selected color even if user closes with X.
        return dlg.currentColor()

    def _pick_control_bar_color(self):
        self._pick_color("control_bar_color")

    def _pick_button_bg_color(self):
        self._pick_color("button_bg_color")

    def _pick_button_hover_color(self):
        self._pick_color("button_hover_color")

    def _pick_timeline_color(self):
        self._pick_color("timeline_color")

    def _pick_timeline_bg_color(self):
        self._pick_color("timeline_bg_color")

    def _pick_text_color(self):
        self._pick_color("text_color")

    def _pick_text_secondary_color(self):
        self._pick_color("text_secondary_color")

    def _pick_speed_start_color(self):
        self._pick_color("speed_gradient_start")

    def _pick_speed_mid_color(self):
        self._pick_color("speed_gradient_mid")

    def _pick_speed_end_color(self):
        self._pick_color("speed_gradient_end")

    def _pick_loop_start_color(self):
        self._pick_color("loop_marker_start_color")

    def _pick_loop_end_color(self):
        self._pick_color("loop_marker_end_color")

    def _reset_layout(self):
        d = self._designer_layout()
        d["controls_row"] = {"offset_x": 0, "offset_y": 0}
        d["timeline_row"] = {"offset_x": 0, "offset_y": 0}
        d["info_row"] = {"offset_x": 0, "offset_y": 0}
        d["component_layouts"] = {}
        d["floating_bleed"] = 80
        d["scaling"] = {"ideal_width": 800, "min_scale": 0.5, "max_scale": 1.0}
        self._load_global_controls()
        self._apply_skin_everywhere()

    def _normalize_and_apply(self):
        self._normalize_for_designer_visibility()
        self._load_global_controls()
        self._apply_skin_everywhere()

    def _save_skin_yaml(self):
        base = Path(__file__).parent.parent / "skins" / "user"
        base.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save Skin", str(base), "YAML Files (*.yaml)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)
        self._current_skin_path = Path(path)
        if self.video_controls:
            self.video_controls.skin_manager.current_skin_path = self._current_skin_path
        if self.video_controls:
            self.video_controls.skin_manager.refresh_available_skins()
        QMessageBox.information(self, "Saved", f"Skin saved to {path}")

    def _slugified_skin_filename(self):
        name = str(self.skin_data.get("name", "custom-skin")).strip().lower()
        name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
        return f"{name or 'custom-skin'}.yaml"

    def _save_current_skin(self):
        """Save skin without prompt to current source file or user skin file."""
        target = self._current_skin_path
        if target is None:
            base = Path(__file__).parent.parent / "skins" / "user"
            base.mkdir(parents=True, exist_ok=True)
            target = base / self._slugified_skin_filename()
        else:
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)

        self._current_skin_path = target
        if self.video_controls:
            self.video_controls.skin_manager.current_skin_path = target
            self.video_controls.skin_manager.refresh_available_skins()
        QMessageBox.information(self, "Saved", f"Saved current skin to:\n{target}")

    def _autosave_current_skin_quiet(self):
        """Autosave without user prompts; safe no-op on failure."""
        try:
            target = self._current_skin_path
            if target is None:
                base = Path(__file__).parent.parent / "skins" / "user"
                base.mkdir(parents=True, exist_ok=True)
                target = base / self._slugified_skin_filename()
            else:
                target = Path(target)
                target.parent.mkdir(parents=True, exist_ok=True)

            with open(target, "w", encoding="utf-8") as f:
                yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)
            self._current_skin_path = target
            if self.video_controls:
                self.video_controls.skin_manager.current_skin_path = target
        except Exception:
            # Non-fatal: don't block editing flow if autosave fails.
            return

    def _restore_all_skins_to_defaults(self):
        """Restore default skins and clear user skins with backup + warning."""
        active_name = None
        if self.video_controls and hasattr(self.video_controls, "skin_manager"):
            active_name = self.video_controls.skin_manager.get_current_skin_name()

        warning = QMessageBox.warning(
            self,
            "Restore All Skins?",
            (
                "This will restore all default skins and remove all user skin YAML files.\n\n"
                "A backup will be created first.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if warning != QMessageBox.StandardButton.Yes:
            return

        skins_root = Path(__file__).parent.parent / "skins"
        defaults_dir = skins_root / "defaults"
        user_dir = skins_root / "user"
        factory_dir = skins_root / "factory_defaults"
        backup_root = skins_root / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_defaults = backup_root / "defaults"
        backup_user = backup_root / "user"
        backup_defaults.mkdir(parents=True, exist_ok=True)
        backup_user.mkdir(parents=True, exist_ok=True)

        for path in defaults_dir.glob("*.yaml"):
            shutil.copy2(path, backup_defaults / path.name)
        for path in user_dir.glob("*.yaml"):
            shutil.copy2(path, backup_user / path.name)

        if not factory_dir.exists():
            factory_dir.mkdir(parents=True, exist_ok=True)
            for path in defaults_dir.glob("*.yaml"):
                shutil.copy2(path, factory_dir / path.name)

        for path in defaults_dir.glob("*.yaml"):
            path.unlink()
        for path in factory_dir.glob("*.yaml"):
            shutil.copy2(path, defaults_dir / path.name)

        for path in user_dir.glob("*.yaml"):
            path.unlink()

        if self.video_controls:
            self.video_controls.skin_manager.refresh_available_skins()
            if not (active_name and self.video_controls.skin_manager.load_skin(active_name)):
                self.video_controls.skin_manager.load_default_skin()
            self.video_controls.apply_current_skin()
            self.skin_data = deepcopy(self.video_controls.skin_manager.current_skin or self._default_skin_data())
            self._current_skin_path = getattr(self.video_controls.skin_manager, "current_skin_path", None)
            self._normalize_for_designer_visibility()
            self._load_global_controls()
            self._apply_skin_everywhere()

        QMessageBox.information(
            self,
            "Skins Restored",
            f"Defaults restored and user skins cleared.\nBackup saved to:\n{backup_root}",
        )

    def _restore_defaults_dialog(self):
        """Ask whether to restore only current skin or all skins."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Restore Defaults")
        msg.setText("Choose restore scope:")
        msg.setInformativeText(
            "Current Skin: restore only the active skin to factory defaults.\n"
            "All Skins: restore all default skins and clear user skins.\n"
            "A backup will be created first."
        )
        current_btn = msg.addButton("Current Skin", QMessageBox.ButtonRole.AcceptRole)
        all_btn = msg.addButton("All Skins", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == current_btn:
            self._restore_current_skin_to_defaults()
        elif clicked == all_btn:
            self._restore_all_skins_to_defaults()

    def _factory_skin_for_current(self):
        """Resolve matching factory skin file path for currently active skin."""
        skins_root = Path(__file__).parent.parent / "skins"
        factory_dir = skins_root / "factory_defaults"
        if not factory_dir.exists():
            return None

        current_name = None
        if self.video_controls and hasattr(self.video_controls, "skin_manager"):
            current_name = self.video_controls.skin_manager.get_current_skin_name()

        # Prefer exact name match inside YAML metadata.
        if current_name:
            for path in factory_dir.glob("*.yaml"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    if str(data.get("name", "")).strip() == str(current_name).strip():
                        return path
                except Exception:
                    continue

        # Fallback: filename match from current path.
        if self._current_skin_path:
            candidate = factory_dir / Path(self._current_skin_path).name
            if candidate.exists():
                return candidate
        return None

    def _restore_current_skin_to_defaults(self):
        """Restore active skin from factory defaults without resetting all skins."""
        factory_src = self._factory_skin_for_current()
        if not factory_src:
            QMessageBox.warning(
                self,
                "No Factory Match",
                "Could not find a factory default file for the current skin.",
            )
            return

        warning = QMessageBox.warning(
            self,
            "Restore Current Skin?",
            "This will overwrite the current skin file with factory defaults.\nA backup will be created first.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if warning != QMessageBox.StandardButton.Yes:
            return

        skins_root = Path(__file__).parent.parent / "skins"
        defaults_dir = skins_root / "defaults"
        backup_root = skins_root / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S_current")
        backup_defaults = backup_root / "defaults"
        backup_defaults.mkdir(parents=True, exist_ok=True)

        target = defaults_dir / factory_src.name
        if target.exists():
            shutil.copy2(target, backup_defaults / target.name)
        shutil.copy2(factory_src, target)

        if self.video_controls:
            active_name = self.video_controls.skin_manager.get_current_skin_name()
            self.video_controls.skin_manager.refresh_available_skins()
            if not self.video_controls.skin_manager.load_skin(active_name):
                self.video_controls.skin_manager.load_default_skin()
            self.video_controls.apply_current_skin()
            self.skin_data = deepcopy(self.video_controls.skin_manager.current_skin or self._default_skin_data())
            self._current_skin_path = getattr(self.video_controls.skin_manager, "current_skin_path", None)
            self._normalize_for_designer_visibility()
            self._load_global_controls()
            self._apply_skin_everywhere()

        QMessageBox.information(
            self,
            "Current Skin Restored",
            f"Current skin restored from factory defaults.\nBackup saved to:\n{backup_root}",
        )

    def _apply_skin_everywhere(self):
        self.live_preview.apply_skin_data(self.skin_data)
        self._refresh_color_button_swatches()
        if self._selected_component:
            QTimer.singleShot(0, lambda: self._move_selection_frame(self._selected_component))
        if self.video_controls and not self._sync_pending:
            self._sync_pending = True
            QTimer.singleShot(25, self._apply_to_main_player_quiet)
        self._autosave_timer.start()

    def _apply_to_main_player_quiet(self):
        self._sync_pending = False
        if self.video_controls:
            self.video_controls.apply_skin_data(self.skin_data)

    def _apply_to_main_player(self):
        if not self.video_controls:
            QMessageBox.information(self, "Info", "No main player attached.")
            return
        self.video_controls.apply_skin_data(self.skin_data)
        QMessageBox.information(self, "Applied", "Changes applied to main player.")

    def closeEvent(self, event):
        """Flush autosave on close for no-button workflow."""
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        self._autosave_current_skin_quiet()
        super().closeEvent(event)
