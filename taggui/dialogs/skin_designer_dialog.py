"""Skin Designer - Visual editor for creating/editing video player skins."""

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QColorDialog, QGroupBox, QGridLayout,
    QLineEdit, QFileDialog, QMessageBox, QComboBox, QScrollArea, QWidget
)
from PySide6.QtGui import QColor
import yaml

from skins.engine import SkinManager, SkinApplier


class SkinDesignerDialog(QDialog):
    """Visual skin designer with live preview."""

    skin_changed = Signal(str)  # Emitted when skin is saved

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle('Skin Designer - Live Visual Editor')
        self.resize(1000, 700)

        self.video_controls = video_controls
        self.skin_manager = SkinManager()
        self.current_skin_data = None
        self.skin_name = "Untitled Skin"

        # Main layout
        main_layout = QHBoxLayout(self)

        # Left side: Controls
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setMinimumWidth(400)

        controls_widget = QWidget()
        self.controls_layout = QVBoxLayout(controls_widget)
        self.controls_layout.setSpacing(10)

        # Build control panels
        self._build_metadata_panel()
        self._build_layout_panel()
        self._build_button_panel()
        self._build_slider_panel()
        self._build_color_panel()
        self._build_reference_panel()

        self.controls_layout.addStretch()
        controls_scroll.setWidget(controls_widget)

        # Right side: Preview + Actions
        right_layout = QVBoxLayout()

        # Preview label
        preview_label = QLabel("Live Preview:")
        preview_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(preview_label)

        # Preview info
        info_label = QLabel("Changes apply to your actual video controls in real-time!\n"
                           "Adjust values on the left and see instant results.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #888; padding: 10px;")
        right_layout.addWidget(info_label)

        right_layout.addStretch()

        # Action buttons
        actions_layout = QVBoxLayout()

        load_btn = QPushButton("📁 Load Existing Skin")
        load_btn.clicked.connect(self._load_skin)
        actions_layout.addWidget(load_btn)

        export_btn = QPushButton("💾 Export to YAML")
        export_btn.clicked.connect(self._export_skin)
        actions_layout.addWidget(export_btn)

        apply_btn = QPushButton("✓ Apply & Close")
        apply_btn.clicked.connect(self._apply_and_close)
        apply_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 10px;")
        actions_layout.addWidget(apply_btn)

        reset_btn = QPushButton("↺ Reset to Classic")
        reset_btn.clicked.connect(self._reset_to_classic)
        actions_layout.addWidget(reset_btn)

        right_layout.addLayout(actions_layout)

        # Add to main layout
        main_layout.addWidget(controls_scroll, 1)
        main_layout.addLayout(right_layout, 1)

        # Load Classic skin as starting point
        self._load_skin_by_name("Classic")

    def _build_metadata_panel(self):
        """Build metadata panel (skin name, author)."""
        group = QGroupBox("Skin Metadata")
        layout = QGridLayout()

        layout.addWidget(QLabel("Skin Name:"), 0, 0)
        self.name_edit = QLineEdit("Untitled Skin")
        self.name_edit.textChanged.connect(lambda text: setattr(self, 'skin_name', text))
        layout.addWidget(self.name_edit, 0, 1)

        layout.addWidget(QLabel("Author:"), 1, 0)
        self.author_edit = QLineEdit("Custom")
        layout.addWidget(self.author_edit, 1, 1)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _build_layout_panel(self):
        """Build layout controls (spacing, sizes)."""
        group = QGroupBox("Layout & Spacing")
        layout = QGridLayout()

        # Control bar height
        label = QLabel("Control Bar Height:")
        label.setToolTip("Property: control_bar_height\nPath: video_player.layout.control_bar_height\n\nHeight of the entire control bar widget (pixels)")
        layout.addWidget(label, 0, 0)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(40, 100)
        self.height_spin.setValue(60)
        self.height_spin.setToolTip("Property: control_bar_height (40-100px)")
        self.height_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.height_spin, 0, 1)

        # Section spacing
        label = QLabel("Section Spacing:")
        label.setToolTip("Property: section_spacing\nPath: video_player.layout.section_spacing\n\nHorizontal space between major sections (pixels)")
        layout.addWidget(label, 1, 0)
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(4, 40)
        self.spacing_spin.setValue(20)
        self.spacing_spin.setToolTip("Property: section_spacing (4-40px)")
        self.spacing_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.spacing_spin, 1, 1)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _build_button_panel(self):
        """Build button controls (size, colors, borders)."""
        group = QGroupBox("Buttons")
        layout = QGridLayout()

        # Button size
        label = QLabel("Button Size:")
        label.setToolTip("Property: button_size\nPath: video_player.styling.button_size\n\nWidth and height of control buttons (play, pause, stop, etc.)")
        layout.addWidget(label, 0, 0)
        self.button_size_spin = QSpinBox()
        self.button_size_spin.setRange(24, 60)
        self.button_size_spin.setValue(40)
        self.button_size_spin.setToolTip("Property: button_size (24-60px)")
        self.button_size_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.button_size_spin, 0, 1)

        # Button spacing
        label = QLabel("Button Spacing:")
        label.setToolTip("Property: button_spacing\nPath: video_player.layout.button_spacing\n\nHorizontal gap between adjacent buttons")
        layout.addWidget(label, 1, 0)
        self.button_spacing_spin = QSpinBox()
        self.button_spacing_spin.setRange(4, 24)
        self.button_spacing_spin.setValue(8)
        self.button_spacing_spin.setToolTip("Property: button_spacing (4-24px)")
        self.button_spacing_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.button_spacing_spin, 1, 1)

        # Border radius
        label = QLabel("Border Radius:")
        label.setToolTip("Property: button_border_radius\nPath: video_player.styling.button_border_radius\n\nRoundness of button corners (0 = square, higher = rounder)")
        layout.addWidget(label, 2, 0)
        self.button_radius_spin = QSpinBox()
        self.button_radius_spin.setRange(0, 20)
        self.button_radius_spin.setValue(4)
        self.button_radius_spin.setToolTip("Property: button_border_radius (0-20px)")
        self.button_radius_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.button_radius_spin, 2, 1)

        # Button background color
        label = QLabel("Background Color:")
        label.setToolTip("Property: button_bg_color\nPath: video_player.styling.button_bg_color\n\nDefault background color of buttons")
        layout.addWidget(label, 3, 0)
        self.button_bg_btn = QPushButton()
        self.button_bg_color = QColor("#2b2b2b")
        self.button_bg_btn.setStyleSheet(f"background-color: {self.button_bg_color.name()}; min-height: 30px;")
        self.button_bg_btn.setToolTip("Property: button_bg_color (hex color)")
        self.button_bg_btn.clicked.connect(lambda: self._pick_color('button_bg'))
        layout.addWidget(self.button_bg_btn, 3, 1)

        # Button hover color
        label = QLabel("Hover Color:")
        label.setToolTip("Property: button_hover_color\nPath: video_player.styling.button_hover_color\n\nBackground color when mouse hovers over button")
        layout.addWidget(label, 4, 0)
        self.button_hover_btn = QPushButton()
        self.button_hover_color = QColor("#3a3a3a")
        self.button_hover_btn.setStyleSheet(f"background-color: {self.button_hover_color.name()}; min-height: 30px;")
        self.button_hover_btn.setToolTip("Property: button_hover_color (hex color)")
        self.button_hover_btn.clicked.connect(lambda: self._pick_color('button_hover'))
        layout.addWidget(self.button_hover_btn, 4, 1)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _build_slider_panel(self):
        """Build slider controls (timeline, speed)."""
        group = QGroupBox("Sliders & Timeline")
        layout = QGridLayout()

        # Timeline height
        label = QLabel("Timeline Height:")
        label.setToolTip("Property: timeline_height\nPath: video_player.styling.timeline_height\n\nVertical thickness of the timeline/progress slider")
        layout.addWidget(label, 0, 0)
        self.timeline_height_spin = QSpinBox()
        self.timeline_height_spin.setRange(4, 20)
        self.timeline_height_spin.setValue(8)
        self.timeline_height_spin.setToolTip("Property: timeline_height (4-20px)")
        self.timeline_height_spin.valueChanged.connect(self._apply_live)
        layout.addWidget(self.timeline_height_spin, 0, 1)

        # Timeline color
        label = QLabel("Timeline Color:")
        label.setToolTip("Property: timeline_color\nPath: video_player.styling.timeline_color\n\nColor of the filled progress portion of timeline slider")
        layout.addWidget(label, 1, 0)
        self.timeline_color_btn = QPushButton()
        self.timeline_color = QColor("#2196F3")
        self.timeline_color_btn.setStyleSheet(f"background-color: {self.timeline_color.name()}; min-height: 30px;")
        self.timeline_color_btn.setToolTip("Property: timeline_color (hex color)")
        self.timeline_color_btn.clicked.connect(lambda: self._pick_color('timeline'))
        layout.addWidget(self.timeline_color_btn, 1, 1)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _build_color_panel(self):
        """Build color controls (background, text, markers)."""
        group = QGroupBox("Colors")
        layout = QGridLayout()

        # Background
        label = QLabel("Background:")
        label.setToolTip("Property: background\nPath: video_player.styling.background\n\nBackground color behind control bar (usually not visible)")
        layout.addWidget(label, 0, 0)
        self.bg_color_btn = QPushButton()
        self.bg_color = QColor("#000000")
        self.bg_color_btn.setStyleSheet(f"background-color: {self.bg_color.name()}; min-height: 30px;")
        self.bg_color_btn.setToolTip("Property: background (hex color)")
        self.bg_color_btn.clicked.connect(lambda: self._pick_color('background'))
        layout.addWidget(self.bg_color_btn, 0, 1)

        # Control bar
        label = QLabel("Control Bar:")
        label.setToolTip("Property: control_bar_color\nPath: video_player.styling.control_bar_color\n\nMain background color of the control bar widget")
        layout.addWidget(label, 1, 0)
        self.control_bar_color_btn = QPushButton()
        self.control_bar_color = QColor("#000000")
        self.control_bar_color_btn.setStyleSheet(f"background-color: {self.control_bar_color.name()}; min-height: 30px;")
        self.control_bar_color_btn.setToolTip("Property: control_bar_color (hex color)")
        self.control_bar_color_btn.clicked.connect(lambda: self._pick_color('control_bar'))
        layout.addWidget(self.control_bar_color_btn, 1, 1)

        # Loop marker start
        label = QLabel("Loop Start Marker:")
        label.setToolTip("Property: loop_marker_start_color\nPath: video_player.styling.loop_marker_start_color\n\nColor of the triangle marker showing loop start position")
        layout.addWidget(label, 2, 0)
        self.loop_start_btn = QPushButton()
        self.loop_start_color = QColor("#FF0080")
        self.loop_start_btn.setStyleSheet(f"background-color: {self.loop_start_color.name()}; min-height: 30px;")
        self.loop_start_btn.setToolTip("Property: loop_marker_start_color (hex color)")
        self.loop_start_btn.clicked.connect(lambda: self._pick_color('loop_start'))
        layout.addWidget(self.loop_start_btn, 2, 1)

        # Loop marker end
        label = QLabel("Loop End Marker:")
        label.setToolTip("Property: loop_marker_end_color\nPath: video_player.styling.loop_marker_end_color\n\nColor of the triangle marker showing loop end position")
        layout.addWidget(label, 3, 0)
        self.loop_end_btn = QPushButton()
        self.loop_end_color = QColor("#FF8C00")
        self.loop_end_btn.setStyleSheet(f"background-color: {self.loop_end_color.name()}; min-height: 30px;")
        self.loop_end_btn.setToolTip("Property: loop_marker_end_color (hex color)")
        self.loop_end_btn.clicked.connect(lambda: self._pick_color('loop_end'))
        layout.addWidget(self.loop_end_btn, 3, 1)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _build_reference_panel(self):
        """Build property reference guide."""
        group = QGroupBox("📖 Property Reference (hover for details)")
        group.setToolTip("Complete list of all skinnable properties.\nHover over any property name to see YAML path and description.")
        layout = QVBoxLayout()

        ref_text = QLabel(
            "<b>Layout Properties:</b><br>"
            "• control_bar_height, button_spacing, section_spacing<br><br>"
            "<b>Button Properties:</b><br>"
            "• button_size, button_bg_color, button_hover_color<br>"
            "• button_border, button_border_radius<br><br>"
            "<b>Slider Properties:</b><br>"
            "• timeline_height, timeline_color, timeline_bg_color<br>"
            "• slider_handle_size, slider_handle_color<br><br>"
            "<b>Loop Marker Properties:</b><br>"
            "• loop_marker_start_color, loop_marker_end_color<br>"
            "• loop_marker_outline, loop_marker_outline_width<br><br>"
            "<b>Speed Slider Gradient:</b><br>"
            "• speed_gradient_start, speed_gradient_mid, speed_gradient_end<br><br>"
            "<b>General Colors:</b><br>"
            "• background, control_bar_color, control_bar_opacity<br>"
            "• text_color, text_secondary_color<br><br>"
            "<b>Borders & Shadows:</b><br>"
            "• borders.radius, borders.control_bar_border<br>"
            "• shadows.control_bar, shadows.button<br><br>"
            "<i>Hover over controls above to see full YAML paths!</i>"
        )
        ref_text.setWordWrap(True)
        ref_text.setStyleSheet("color: #888; font-size: 10px; padding: 10px;")
        layout.addWidget(ref_text)

        group.setLayout(layout)
        self.controls_layout.addWidget(group)

    def _pick_color(self, color_type: str):
        """Open color picker and apply color."""
        # Get current color
        current_colors = {
            'button_bg': self.button_bg_color,
            'button_hover': self.button_hover_color,
            'timeline': self.timeline_color,
            'background': self.bg_color,
            'control_bar': self.control_bar_color,
            'loop_start': self.loop_start_color,
            'loop_end': self.loop_end_color
        }

        current_color = current_colors.get(color_type, QColor("#FFFFFF"))

        # Open color dialog
        color = QColorDialog.getColor(current_color, self, f"Pick {color_type.replace('_', ' ').title()} Color")

        if color.isValid():
            # Update color
            if color_type == 'button_bg':
                self.button_bg_color = color
                self.button_bg_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'button_hover':
                self.button_hover_color = color
                self.button_hover_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'timeline':
                self.timeline_color = color
                self.timeline_color_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'background':
                self.bg_color = color
                self.bg_color_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'control_bar':
                self.control_bar_color = color
                self.control_bar_color_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'loop_start':
                self.loop_start_color = color
                self.loop_start_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")
            elif color_type == 'loop_end':
                self.loop_end_color = color
                self.loop_end_btn.setStyleSheet(f"background-color: {color.name()}; min-height: 30px;")

            self._apply_live()

    def _apply_live(self):
        """Apply current settings to video controls immediately."""
        if not self.video_controls:
            return

        # Build skin data from current controls
        skin_data = self._build_skin_data()

        # Create temporary skin applier
        applier = SkinApplier(skin_data)

        # Apply to video controls
        self.video_controls.current_applier = applier
        self.video_controls.apply_current_skin()

    def _build_skin_data(self):
        """Build skin data dict from current control values."""
        return {
            'name': self.skin_name,
            'author': self.author_edit.text(),
            'version': '1.0',
            'video_player': {
                'layout': {
                    'control_bar_height': self.height_spin.value(),
                    'button_spacing': self.button_spacing_spin.value(),
                    'section_spacing': self.spacing_spin.value(),
                    'control_bar_position': 'bottom',
                    'button_alignment': 'center',
                    'timeline_position': 'above'
                },
                'styling': {
                    'background': self.bg_color.name(),
                    'control_bar_color': self.control_bar_color.name(),
                    'control_bar_opacity': 0.80,
                    'button_size': self.button_size_spin.value(),
                    'button_bg_color': self.button_bg_color.name(),
                    'button_hover_color': self.button_hover_color.name(),
                    'button_border': f"2px solid #555555",
                    'button_border_radius': self.button_radius_spin.value(),
                    'timeline_height': self.timeline_height_spin.value(),
                    'timeline_color': self.timeline_color.name(),
                    'timeline_bg_color': '#1A1A1A',
                    'slider_handle_size': 16,
                    'slider_handle_color': '#FFFFFF',
                    'slider_handle_border': '2px solid #333333',
                    'loop_marker_start_color': self.loop_start_color.name(),
                    'loop_marker_end_color': self.loop_end_color.name(),
                    'loop_marker_outline': '#FFFFFF',
                    'loop_marker_outline_width': 2,
                    'speed_gradient_start': '#2D5A2D',
                    'speed_gradient_mid': '#6B8E23',
                    'speed_gradient_end': '#32CD32',
                    'text_color': '#FFFFFF',
                    'text_secondary_color': '#B0B0B0',
                    'label_font_size': 12
                },
                'borders': {
                    'radius': self.button_radius_spin.value(),
                    'control_bar_border': 'none',
                    'button_border': '2px solid #555555'
                },
                'shadows': {
                    'control_bar': 'none',
                    'button': 'none',
                    'overlay': 'none'
                }
            }
        }

    def _export_skin(self):
        """Export current skin to YAML file."""
        # Get save location
        default_name = self.skin_name.lower().replace(' ', '-') + '.yaml'
        skins_user_dir = Path(__file__).parent.parent / 'skins' / 'user'
        skins_user_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Skin",
            str(skins_user_dir / default_name),
            "YAML Files (*.yaml *.yml)"
        )

        if not file_path:
            return

        # Build skin data
        skin_data = self._build_skin_data()

        # Write to file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(skin_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            QMessageBox.information(
                self,
                "Skin Exported",
                f"Skin exported successfully to:\n{file_path}\n\n"
                f"It will appear in the skin selector after restarting TagGUI."
            )

            self.skin_changed.emit(self.skin_name)

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export skin:\n{e}")

    def _load_skin(self):
        """Load existing skin for editing."""
        skins_dir = Path(__file__).parent.parent / 'skins'

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Skin",
            str(skins_dir),
            "YAML Files (*.yaml *.yml)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                skin_data = yaml.safe_load(f)

            self._load_skin_from_data(skin_data)

        except Exception as e:
            QMessageBox.critical(self, "Load Failed", f"Failed to load skin:\n{e}")

    def _load_skin_by_name(self, name: str):
        """Load skin by name from available skins."""
        for skin in self.skin_manager.get_available_skins():
            if skin['name'] == name:
                self._load_skin_from_data(skin['data'])
                return

    def _load_skin_from_data(self, skin_data: dict):
        """Load skin values into controls."""
        self.name_edit.setText(skin_data.get('name', 'Untitled'))
        self.author_edit.setText(skin_data.get('author', 'Custom'))

        vp = skin_data.get('video_player', {})
        layout = vp.get('layout', {})
        styling = vp.get('styling', {})
        borders = vp.get('borders', {})

        # Layout
        self.height_spin.setValue(layout.get('control_bar_height', 60))
        self.spacing_spin.setValue(layout.get('section_spacing', 20))

        # Buttons
        self.button_size_spin.setValue(styling.get('button_size', 40))
        self.button_spacing_spin.setValue(layout.get('button_spacing', 8))
        self.button_radius_spin.setValue(borders.get('radius', 4))
        self.button_bg_color = QColor(styling.get('button_bg_color', '#2b2b2b'))
        self.button_bg_btn.setStyleSheet(f"background-color: {self.button_bg_color.name()}; min-height: 30px;")
        self.button_hover_color = QColor(styling.get('button_hover_color', '#3a3a3a'))
        self.button_hover_btn.setStyleSheet(f"background-color: {self.button_hover_color.name()}; min-height: 30px;")

        # Sliders
        self.timeline_height_spin.setValue(styling.get('timeline_height', 8))
        self.timeline_color = QColor(styling.get('timeline_color', '#2196F3'))
        self.timeline_color_btn.setStyleSheet(f"background-color: {self.timeline_color.name()}; min-height: 30px;")

        # Colors
        self.bg_color = QColor(styling.get('background', '#000000'))
        self.bg_color_btn.setStyleSheet(f"background-color: {self.bg_color.name()}; min-height: 30px;")
        self.control_bar_color = QColor(styling.get('control_bar_color', '#000000'))
        self.control_bar_color_btn.setStyleSheet(f"background-color: {self.control_bar_color.name()}; min-height: 30px;")
        self.loop_start_color = QColor(styling.get('loop_marker_start_color', '#FF0080'))
        self.loop_start_btn.setStyleSheet(f"background-color: {self.loop_start_color.name()}; min-height: 30px;")
        self.loop_end_color = QColor(styling.get('loop_marker_end_color', '#FF8C00'))
        self.loop_end_btn.setStyleSheet(f"background-color: {self.loop_end_color.name()}; min-height: 30px;")

        # Apply live
        self._apply_live()

    def _reset_to_classic(self):
        """Reset all values to Classic skin."""
        self._load_skin_by_name("Classic")

    def _apply_and_close(self):
        """Apply current skin and close dialog."""
        self._apply_live()
        self.accept()
