"""Live player skin designer (v1): interact with real controls, not a mockup."""

from copy import deepcopy
from pathlib import Path
import yaml

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QColor
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
    QVBoxLayout,
    QWidget,
)

from widgets.video_controls import VideoControlsWidget


class SkinDesignerLive(QDialog):
    """Simple live skin designer bound to the real player widget structure."""

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle("Live Skin Designer (Simple)")
        self.resize(1200, 520)

        self.video_controls = video_controls
        if video_controls and video_controls.skin_manager.current_skin:
            self.skin_data = deepcopy(video_controls.skin_manager.current_skin)
        else:
            self.skin_data = self._default_skin_data()
        self._normalize_for_designer_visibility()

        self._selected_component = None
        self._sync_pending = False

        root = QHBoxLayout(self)

        # Left: real player instance for click-select
        left = QVBoxLayout()
        left.addWidget(QLabel("Live Player Surface"))
        self.live_preview = VideoControlsWidget(self)
        self.live_preview.setMinimumHeight(180)
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

        save_btn = QPushButton("Save Skin YAML")
        save_btn.clicked.connect(self._save_skin_yaml)
        panel_layout.addWidget(save_btn)

        apply_btn = QPushButton("Apply To Main Player")
        apply_btn.clicked.connect(self._apply_to_main_player)
        panel_layout.addWidget(apply_btn)

        root.addWidget(panel, 1)

        self._component_widgets = self._build_component_map()
        self._install_click_handlers()
        self._load_global_controls()
        self._apply_skin_everywhere()

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

        self.color_btn = QPushButton("Pick Color")
        self.color_btn.clicked.connect(self._on_pick_color)
        grid.addWidget(self.color_btn, 1, 0, 1, 2)

        grid.addWidget(QLabel("Opacity"), 2, 0)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        grid.addWidget(self.opacity_slider, 2, 1)

        grid.addWidget(QLabel("Offset X"), 3, 0)
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-500, 500)
        self.offset_x_spin.valueChanged.connect(self._on_offset_changed)
        grid.addWidget(self.offset_x_spin, 3, 1)

        grid.addWidget(QLabel("Offset Y"), 4, 0)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-200, 200)
        self.offset_y_spin.valueChanged.connect(self._on_offset_changed)
        grid.addWidget(self.offset_y_spin, 4, 1)

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
        self.loop_end_btn = self._add_color_button(grid, r, "Loop End", self._pick_loop_end_color)
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

    def _add_color_button(self, grid, row, label, callback):
        grid.addWidget(QLabel(label), row, 0)
        btn = QPushButton("Pick")
        btn.clicked.connect(callback)
        grid.addWidget(btn, row, 1)
        return btn

    def _load_global_controls(self):
        self._loading_global = True
        layout = self._layout_cfg()
        styling = self._styling_cfg()
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

        self.controls_x_spin.setValue(int(controls.get("offset_x", 0)))
        self.controls_y_spin.setValue(int(controls.get("offset_y", 0)))
        self.timeline_x_spin.setValue(int(timeline.get("offset_x", 0)))
        self.timeline_y_spin.setValue(int(timeline.get("offset_y", 0)))
        self.info_x_spin.setValue(int(info.get("offset_x", 0)))
        self.info_y_spin.setValue(int(info.get("offset_y", 0)))

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
                    "button_spacing": 8,
                    "section_spacing": 20,
                },
                "styling": {
                    "control_bar_color": "#000000",
                    "control_bar_opacity": 0.8,
                    "button_size": 40,
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
                    "text_color": "#FFFFFF",
                    "text_secondary_color": "#B0B0B0",
                    "label_font_size": 12,
                },
                "designer_layout": {
                    "controls_row": {"offset_x": 0, "offset_y": 0},
                    "timeline_row": {"offset_x": 0, "offset_y": 0},
                    "info_row": {"offset_x": 0, "offset_y": 0},
                    "scaling": {"ideal_width": 800, "min_scale": 0.5, "max_scale": 1.0},
                },
            },
        }

    def _normalize_for_designer_visibility(self):
        """Clamp risky values so live preview remains visible/clickable."""
        styling = self._styling_cfg()
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

        layout["control_bar_height"] = max(40, min(180, int(layout.get("control_bar_height", 60))))
        layout["button_spacing"] = max(0, min(40, int(layout.get("button_spacing", 8))))
        layout["section_spacing"] = max(0, min(80, int(layout.get("section_spacing", 20))))
        if layout.get("button_alignment") not in ("left", "center", "right"):
            layout["button_alignment"] = "center"
        if layout.get("timeline_position") not in ("above", "below"):
            layout["timeline_position"] = "above"

        for row in (controls, timeline, info):
            row["offset_x"] = max(-180, min(180, int(row.get("offset_x", 0))))
            row["offset_y"] = max(-80, min(80, int(row.get("offset_y", 0))))

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
        row = self._designer_layout().setdefault(self._row_key_for_component(component_id), {})

        # Size key by type
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            size = int(block.get("button_size", self.skin_data["video_player"]["styling"].get("button_size", 40)))
        elif "label" in component_id:
            size = int(block.get("label_font_size", self.skin_data["video_player"]["styling"].get("label_font_size", 12)))
        elif component_id == "timeline_slider":
            size = int(block.get("timeline_height", self.skin_data["video_player"]["styling"].get("timeline_height", 8)))
        else:
            size = int(block.get("slider_handle_size", self.skin_data["video_player"]["styling"].get("slider_handle_size", 16)))
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(size)
        self.size_spin.blockSignals(False)

        opacity = float(block.get("opacity", 1.0))
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(max(0.0, min(1.0, opacity)) * 100))
        self.opacity_slider.blockSignals(False)

        self.offset_x_spin.blockSignals(True)
        self.offset_y_spin.blockSignals(True)
        self.offset_x_spin.setValue(int(row.get("offset_x", 0)))
        self.offset_y_spin.setValue(int(row.get("offset_y", 0)))
        self.offset_x_spin.blockSignals(False)
        self.offset_y_spin.blockSignals(False)

    def _on_size_changed(self, value):
        if not self._selected_component:
            return
        block = self._component_style_block(self._selected_component)
        component_id = self._selected_component
        if component_id.endswith("_button") or component_id == "loop_checkbox":
            block["button_size"] = int(value)
            self.skin_data["video_player"]["styling"]["button_size"] = int(value)
        elif "label" in component_id:
            block["label_font_size"] = int(value)
        elif component_id == "timeline_slider":
            block["timeline_height"] = int(value)
        else:
            block["slider_handle_size"] = int(value)
        self._apply_skin_everywhere()

    def _on_pick_color(self):
        if not self._selected_component:
            return
        color = QColorDialog.getColor(QColor("#FFFFFF"), self, "Pick Color")
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
        row_key = self._row_key_for_component(self._selected_component)
        row = self._designer_layout().setdefault(row_key, {})
        row["offset_x"] = int(self.offset_x_spin.value())
        row["offset_y"] = int(self.offset_y_spin.value())
        self._apply_skin_everywhere()

    def _on_global_changed(self):
        if self._loading_global:
            return
        layout = self._layout_cfg()
        styling = self._styling_cfg()
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

        controls["offset_x"] = int(self.controls_x_spin.value())
        controls["offset_y"] = int(self.controls_y_spin.value())
        timeline["offset_x"] = int(self.timeline_x_spin.value())
        timeline["offset_y"] = int(self.timeline_y_spin.value())
        info["offset_x"] = int(self.info_x_spin.value())
        info["offset_y"] = int(self.info_y_spin.value())

        scaling["ideal_width"] = int(self.scale_ideal_spin.value())
        scaling["min_scale"] = float(self.scale_min_spin.value()) / 100.0
        scaling["max_scale"] = float(self.scale_max_spin.value()) / 100.0
        self._apply_skin_everywhere()

    def _pick_color(self, key):
        current = self._styling_cfg().get(key, "#FFFFFF")
        color = QColorDialog.getColor(QColor(current), self, f"Pick {key}")
        if not color.isValid():
            return
        self._styling_cfg()[key] = color.name()
        self._apply_skin_everywhere()

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
        if self.video_controls:
            self.video_controls.skin_manager.refresh_available_skins()
        QMessageBox.information(self, "Saved", f"Skin saved to {path}")

    def _apply_skin_everywhere(self):
        self.live_preview.apply_skin_data(self.skin_data)
        if self._selected_component:
            QTimer.singleShot(0, lambda: self._move_selection_frame(self._selected_component))
        if self.video_controls and not self._sync_pending:
            self._sync_pending = True
            QTimer.singleShot(25, self._apply_to_main_player_quiet)

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
