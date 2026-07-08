"""Visual Interactive Skin Designer - Drag, drop, click to edit."""

from pathlib import Path
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QRect, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem,
    QColorDialog, QFileDialog, QMessageBox, QLabel, QSpinBox,
    QGroupBox, QGridLayout, QWidget, QScrollArea
)
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QFont
import yaml

from skins.engine import SkinApplier


class DraggableElement(QGraphicsRectItem):
    """Draggable UI element in the canvas."""

    def __init__(self, x, y, w, h, element_type, property_name, parent_designer):
        super().__init__(0, 0, w, h)
        self.element_type = element_type  # "button", "slider", "label"
        self.property_name = property_name
        self.designer = parent_designer

        # Visual properties
        self.setPos(x, y)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Default styling
        self.default_pen = QPen(QColor("#555555"), 2)
        self.selected_pen = QPen(QColor("#2196F3"), 3)
        self.setPen(self.default_pen)
        self.setBrush(QBrush(QColor("#2b2b2b")))

        # Label
        self.label = QGraphicsTextItem(property_name, self)
        self.label.setDefaultTextColor(QColor("#FFFFFF"))
        font = QFont()
        font.setPointSize(8)
        self.label.setFont(font)
        self.label.setPos(5, h/2 - 10)

    def itemChange(self, change, value):
        """Handle selection and movement."""
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.isSelected():
                self.setPen(self.selected_pen)
                self.designer.element_selected(self)
            else:
                self.setPen(self.default_pen)

        elif change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            # Update skin data when moved
            self.designer.update_element_position(self)

        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        """Right-click to change color."""
        if self.element_type == "button":
            current_color = self.brush().color()
            color = QColorDialog.getColor(current_color, None, f"Pick Color for {self.property_name}")
            if color.isValid():
                self.setBrush(QBrush(color))
                self.designer.update_element_color(self, color)


class SkinDesignerVisual(QDialog):
    """Interactive visual skin designer with drag-and-drop."""

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle('🎨 Skin Designer - Visual Editor')
        self.resize(1200, 800)

        self.video_controls = video_controls
        self.selected_element = None
        self.skin_name = "Custom Skin"

        # Current skin data
        self.skin_data = self._get_default_skin_data()

        # Main layout
        main_layout = QHBoxLayout(self)

        # Left: Canvas
        canvas_layout = QVBoxLayout()

        # Canvas title
        title = QLabel("🎮 Drag elements • Right-click for colors • Select to edit properties")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 10px;")
        canvas_layout.addWidget(title)

        # Graphics scene/view
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 800, 400)
        self.scene.setBackgroundBrush(QBrush(QColor("#0D0D0D")))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setMinimumSize(820, 420)
        canvas_layout.addWidget(self.view)

        # Instructions
        instructions = QLabel(
            "💡 TIP: Drag buttons to reposition • Right-click to change colors • "
            "Click to select and edit size in properties panel →"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #888; padding: 10px;")
        canvas_layout.addWidget(instructions)

        # Build canvas elements
        self._build_canvas()

        # Right: Properties panel
        props_scroll = QScrollArea()
        props_scroll.setWidgetResizable(True)
        props_scroll.setMaximumWidth(350)

        props_widget = QWidget()
        self.props_layout = QVBoxLayout(props_widget)

        self._build_properties_panel()

        props_scroll.setWidget(props_widget)

        # Add to main layout
        main_layout.addLayout(canvas_layout, 2)
        main_layout.addWidget(props_scroll, 1)

    def _get_default_skin_data(self):
        """Get default skin structure."""
        return {
            'name': self.skin_name,
            'version': '1.0',
            'author': 'Custom',
            'video_player': {
                'layout': {
                    'control_bar_height': 60,
                    'button_spacing': 8,
                    'section_spacing': 20
                },
                'styling': {
                    'background': '#000000',
                    'control_bar_color': '#000000',
                    'control_bar_opacity': 0.80,
                    'button_size': 40,
                    'button_bg_color': '#2b2b2b',
                    'button_hover_color': '#3a3a3a',
                    'button_border': '2px solid #555555',
                    'button_border_radius': 4,
                    'timeline_height': 8,
                    'timeline_color': '#2196F3',
                    'timeline_bg_color': '#1A1A1A',
                    'loop_marker_start_color': '#FF0080',
                    'loop_marker_end_color': '#FF8C00',
                    'speed_gradient_start': '#2D5A2D',
                    'speed_gradient_mid': '#6B8E23',
                    'speed_gradient_end': '#32CD32',
                    'text_color': '#FFFFFF'
                },
                'borders': {'radius': 4},
                'shadows': {'control_bar': 'none', 'button': 'none'}
            }
        }

    def _build_canvas(self):
        """Build interactive canvas with draggable elements."""
        # Control bar background
        control_bar = QGraphicsRectItem(0, 0, 800, 60)
        control_bar.setBrush(QBrush(QColor("#000000")))
        control_bar.setOpacity(0.8)
        self.scene.addItem(control_bar)

        # Buttons row
        button_y = 10
        button_size = 40
        x_pos = 50

        buttons = [
            ("Play", "button_bg_color"),
            ("Stop", "button_bg_color"),
            ("Mute", "button_bg_color"),
        ]

        self.elements = []
        for btn_name, prop in buttons:
            btn = DraggableElement(x_pos, button_y, button_size, button_size, "button", btn_name, self)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x_pos += button_size + 8

        # Section spacing
        x_pos += 12

        # Frame nav buttons
        nav_buttons = [
            ("<<", "button_bg_color"),
            ("<", "button_bg_color"),
            (">", "button_bg_color"),
            (">>", "button_bg_color"),
        ]

        for btn_name, prop in nav_buttons:
            btn = DraggableElement(x_pos, button_y, button_size, button_size, "button", btn_name, self)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x_pos += button_size + 8

        # Timeline slider (below buttons)
        timeline = DraggableElement(50, 80, 700, 8, "slider", "Timeline", self)
        timeline.setBrush(QBrush(QColor("#2196F3")))
        timeline.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)  # Don't move timeline
        self.scene.addItem(timeline)
        self.elements.append(timeline)

        # Loop markers (triangles on timeline)
        # Just visual indicators for now
        start_marker_label = QGraphicsTextItem("▼ Start")
        start_marker_label.setDefaultTextColor(QColor("#FF0080"))
        start_marker_label.setPos(100, 95)
        self.scene.addItem(start_marker_label)

        end_marker_label = QGraphicsTextItem("▼ End")
        end_marker_label.setDefaultTextColor(QColor("#FF8C00"))
        end_marker_label.setPos(600, 95)
        self.scene.addItem(end_marker_label)

    def _build_properties_panel(self):
        """Build properties panel for selected element."""
        # Title
        self.selected_label = QLabel("No element selected")
        self.selected_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 10px;")
        self.props_layout.addWidget(self.selected_label)

        # Size controls
        size_group = QGroupBox("Size & Position")
        size_layout = QGridLayout()

        size_layout.addWidget(QLabel("Width:"), 0, 0)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(20, 100)
        self.width_spin.setValue(40)
        self.width_spin.valueChanged.connect(self._update_selected_size)
        size_layout.addWidget(self.width_spin, 0, 1)

        size_layout.addWidget(QLabel("Height:"), 1, 0)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(20, 100)
        self.height_spin.setValue(40)
        self.height_spin.valueChanged.connect(self._update_selected_size)
        size_layout.addWidget(self.height_spin, 1, 1)

        size_group.setLayout(size_layout)
        self.props_layout.addWidget(size_group)

        # Color controls
        color_group = QGroupBox("Colors")
        color_layout = QVBoxLayout()

        self.bg_color_btn = QPushButton("Background Color")
        self.bg_color_btn.clicked.connect(self._pick_bg_color)
        color_layout.addWidget(self.bg_color_btn)

        self.hover_color_btn = QPushButton("Hover Color")
        self.hover_color_btn.clicked.connect(self._pick_hover_color)
        color_layout.addWidget(self.hover_color_btn)

        color_group.setLayout(color_layout)
        self.props_layout.addWidget(color_group)

        self.props_layout.addStretch()

        # Actions
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()

        export_btn = QPushButton("💾 Export Skin")
        export_btn.clicked.connect(self._export_skin)
        actions_layout.addWidget(export_btn)

        apply_btn = QPushButton("✓ Apply Live")
        apply_btn.clicked.connect(self._apply_live)
        apply_btn.setStyleSheet("background-color: #2196F3; color: white;")
        actions_layout.addWidget(apply_btn)

        load_btn = QPushButton("📁 Load Skin")
        load_btn.clicked.connect(self._load_skin)
        actions_layout.addWidget(load_btn)

        actions_group.setLayout(actions_layout)
        self.props_layout.addWidget(actions_group)

    def element_selected(self, element):
        """Called when an element is selected."""
        self.selected_element = element
        self.selected_label.setText(f"Selected: {element.property_name}")

        # Update spinboxes
        rect = element.rect()
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(int(rect.width()))
        self.height_spin.setValue(int(rect.height()))
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)

    def update_element_position(self, element):
        """Called when element is moved."""
        # Update skin data based on new position
        pass  # Positions are relative, handled by layout in export

    def update_element_color(self, element, color):
        """Called when element color changes via right-click."""
        # Update skin data
        self.skin_data['video_player']['styling']['button_bg_color'] = color.name()
        self._apply_live()

    def _update_selected_size(self):
        """Update selected element size from spinboxes."""
        if not self.selected_element:
            return

        w = self.width_spin.value()
        h = self.height_spin.value()

        rect = self.selected_element.rect()
        rect.setWidth(w)
        rect.setHeight(h)
        self.selected_element.setRect(rect)

        # Update skin data
        if self.selected_element.element_type == "button":
            self.skin_data['video_player']['styling']['button_size'] = max(w, h)
        elif self.selected_element.element_type == "slider":
            self.skin_data['video_player']['styling']['timeline_height'] = h

        self._apply_live()

    def _pick_bg_color(self):
        """Pick background color for selected element."""
        if not self.selected_element:
            return

        current = self.selected_element.brush().color()
        color = QColorDialog.getColor(current, self, "Background Color")
        if color.isValid():
            self.selected_element.setBrush(QBrush(color))
            self.skin_data['video_player']['styling']['button_bg_color'] = color.name()
            self._apply_live()

    def _pick_hover_color(self):
        """Pick hover color."""
        current_hex = self.skin_data['video_player']['styling'].get('button_hover_color', '#3a3a3a')
        current = QColor(current_hex)
        color = QColorDialog.getColor(current, self, "Hover Color")
        if color.isValid():
            self.skin_data['video_player']['styling']['button_hover_color'] = color.name()
            self._apply_live()

    def _apply_live(self):
        """Apply current skin to video controls immediately."""
        if not self.video_controls:
            return

        applier = SkinApplier(self.skin_data)
        self.video_controls.current_applier = applier
        self.video_controls.apply_current_skin()

    def _export_skin(self):
        """Export skin to YAML."""
        skins_user_dir = Path(__file__).parent.parent / 'skins' / 'user'
        skins_user_dir.mkdir(parents=True, exist_ok=True)

        default_name = self.skin_name.lower().replace(' ', '-') + '.yaml'
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Skin", str(skins_user_dir / default_name), "YAML Files (*.yaml)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)

            QMessageBox.information(self, "Exported", f"Skin saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export failed:\n{e}")

    def _load_skin(self):
        """Load existing skin."""
        skins_dir = Path(__file__).parent.parent / 'skins'
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Skin", str(skins_dir), "YAML Files (*.yaml)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.skin_data = yaml.safe_load(f)

            self.skin_name = self.skin_data.get('name', 'Custom')
            self._apply_live()
            QMessageBox.information(self, "Loaded", f"Loaded: {self.skin_name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Load failed:\n{e}")
