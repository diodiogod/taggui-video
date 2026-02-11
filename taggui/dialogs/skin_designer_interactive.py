"""Fully Interactive Skin Designer - Pure visual editing, no settings panels."""

from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QColorDialog, QFileDialog, QMessageBox, QLabel,
    QSlider, QFontDialog, QWidget, QGridLayout
)
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QFont, QRadialGradient
import yaml

from skins.engine import SkinApplier


class ResizeHandle(QGraphicsEllipseItem):
    """Corner handle for resizing elements."""

    def __init__(self, parent_element):
        super().__init__(-5, -5, 10, 10)
        self.parent_element = parent_element
        self._dragging = False
        self._drag_start = None
        self.setBrush(QBrush(QColor("#2196F3")))
        self.setPen(QPen(QColor("#FFFFFF"), 2))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setZValue(100)

    def mousePressEvent(self, event):
        """Start resize drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.scenePos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle resize drag."""
        if self._dragging:
            # Calculate new size based on mouse position in parent coordinates
            mouse_pos_in_parent = self.parentItem().mapFromScene(event.scenePos())
            self.parent_element.resize_to_point(mouse_pos_in_parent)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End resize drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_start = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class InteractiveElement(QGraphicsRectItem):
    """Fully interactive UI element - drag to move, drag corners to resize."""

    def __init__(self, x, y, w, h, element_type, label_text, designer):
        super().__init__(0, 0, w, h)
        self.element_type = element_type
        self.label_text = label_text
        self.designer = designer
        self.bg_color = QColor("#2b2b2b")
        self.hover_color = QColor("#3a3a3a")
        self.opacity_value = 1.0
        self._updating = False  # Prevent recursion during resize

        self.setPos(x, y)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Visual styling
        self.default_pen = QPen(QColor("#555555"), 2)
        self.selected_pen = QPen(QColor("#2196F3"), 3)
        self.setPen(self.default_pen)
        self.setBrush(QBrush(self.bg_color))
        self.setOpacity(self.opacity_value)

        # Label
        self.label = QGraphicsTextItem(label_text, self)
        self.label.setDefaultTextColor(QColor("#FFFFFF"))
        font = QFont("Arial", 9, QFont.Weight.Bold)
        self.label.setFont(font)
        self._center_label()

        # Resize handle (hidden initially)
        # Note: Parent is set in ResizeHandle constructor via QGraphicsItem(self)
        self.resize_handle = None  # Will be created on first selection

        # Glow effect
        self.glow_effect = None

    def _center_label(self):
        """Center label in element."""
        rect = self.rect()
        label_rect = self.label.boundingRect()
        x = (rect.width() - label_rect.width()) / 2
        y = (rect.height() - label_rect.height()) / 2
        self.label.setPos(x, y)

    def resize_to_point(self, point):
        """Resize element to given point (in local coordinates)."""
        if self._updating:
            return

        self._updating = True

        # Point is where the mouse is, make that the new bottom-right corner
        new_width = max(20, point.x())
        new_height = max(20, point.y())

        rect = self.rect()
        rect.setWidth(new_width)
        rect.setHeight(new_height)
        self.setRect(rect)

        # Reposition handle at new bottom-right corner
        if self.resize_handle:
            self.resize_handle.setPos(new_width, new_height)

        self._center_label()

        # Update skin data
        self.designer.update_element_size(self, new_width, new_height)

        self._updating = False

    def itemChange(self, change, value):
        """Handle selection."""
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.isSelected():
                self.setPen(self.selected_pen)

                # Create resize handle on first selection
                if self.resize_handle is None:
                    self.resize_handle = ResizeHandle(self)
                    self.resize_handle.setParentItem(self)

                self.resize_handle.show()
                # Position handle at bottom-right
                rect = self.rect()
                self.resize_handle.setPos(rect.width(), rect.height())
                self._add_glow()
                self.designer.element_selected(self)
            else:
                self.setPen(self.default_pen)
                if self.resize_handle:
                    self.resize_handle.hide()
                self._remove_glow()

        return super().itemChange(change, value)

    def _add_glow(self):
        """Add glowing outline effect."""
        # Create glow by drawing larger semi-transparent outline
        self.setPen(QPen(QColor(33, 150, 243, 150), 6))

    def _remove_glow(self):
        """Remove glow effect."""
        self.setPen(self.default_pen if not self.isSelected() else self.selected_pen)

    def contextMenuEvent(self, event):
        """Right-click for color/font picker."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        # Prevent menu on invalid events
        if not event or not event.screenPos():
            return

        menu = QMenu()

        # Color picker action
        color_action = QAction("🎨 Change Color", menu)
        color_action.triggered.connect(self._pick_color)
        menu.addAction(color_action)

        # Opacity action
        opacity_action = QAction("🔆 Adjust Opacity", menu)
        opacity_action.triggered.connect(self._pick_opacity)
        menu.addAction(opacity_action)

        if self.element_type == "label":
            # Font picker for labels
            font_action = QAction("🔤 Change Font", menu)
            font_action.triggered.connect(self._pick_font)
            menu.addAction(font_action)

        menu.exec(event.screenPos())
        event.accept()

    def _pick_color(self):
        """Color picker with opacity."""
        try:
            dialog = ColorOpacityDialog(self.bg_color, self.opacity_value, self.designer)
            if dialog.exec():
                self.bg_color = dialog.selected_color
                self.opacity_value = dialog.selected_opacity
                self.setBrush(QBrush(self.bg_color))
                self.setOpacity(self.opacity_value)
                self.designer.update_element_color(self, self.bg_color, self.opacity_value)
        except Exception as e:
            print(f"Error in color picker: {e}")
            import traceback
            traceback.print_exc()

    def _pick_opacity(self):
        """Quick opacity picker."""
        dialog = OpacityDialog(self.opacity_value, self.designer)
        if dialog.exec():
            self.opacity_value = dialog.selected_opacity
            self.setOpacity(self.opacity_value)
            self.designer.update_element_opacity(self, self.opacity_value)

    def _pick_font(self):
        """Font picker dialog."""
        current_font = self.label.font()
        result = QFontDialog.getFont(current_font, self.designer, "Select Font")
        if isinstance(result, tuple) and len(result) == 2:
            font, ok = result
            if ok and isinstance(font, QFont):
                self.label.setFont(font)
                self._center_label()
                self.designer.update_element_font(self, font)


class ColorOpacityDialog(QDialog):
    """Custom color picker with opacity slider."""

    def __init__(self, current_color, current_opacity, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color & Opacity")
        self.selected_color = current_color
        self.selected_opacity = current_opacity

        layout = QVBoxLayout(self)

        # Color preview
        self.preview = QLabel()
        self.preview.setFixedHeight(60)
        self.preview.setStyleSheet(f"background-color: {current_color.name()}; border: 2px solid #555;")
        layout.addWidget(self.preview)

        # Color picker button
        color_btn = QPushButton("🎨 Pick Color")
        color_btn.clicked.connect(self._pick_color)
        layout.addWidget(color_btn)

        # Opacity slider
        opacity_label = QLabel(f"Opacity: {int(current_opacity * 100)}%")
        layout.addWidget(opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(current_opacity * 100))
        self.opacity_slider.valueChanged.connect(
            lambda v: opacity_label.setText(f"Opacity: {v}%")
        )
        layout.addWidget(self.opacity_slider)

        # OK/Cancel
        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _pick_color(self):
        """Open color picker."""
        color = QColorDialog.getColor(self.selected_color, self, "Pick Color")
        if color.isValid():
            self.selected_color = color
            self.preview.setStyleSheet(f"background-color: {color.name()}; border: 2px solid #555;")

    def accept(self):
        """Save opacity on accept."""
        self.selected_opacity = self.opacity_slider.value() / 100.0
        super().accept()


class OpacityDialog(QDialog):
    """Quick opacity-only dialog."""

    def __init__(self, current_opacity, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adjust Opacity")
        self.selected_opacity = current_opacity

        layout = QVBoxLayout(self)

        label = QLabel(f"Opacity: {int(current_opacity * 100)}%")
        layout.addWidget(label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(current_opacity * 100))
        self.slider.valueChanged.connect(lambda v: label.setText(f"Opacity: {v}%"))
        layout.addWidget(self.slider)

        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def accept(self):
        self.selected_opacity = self.slider.value() / 100.0
        super().accept()


class SkinDesignerInteractive(QDialog):
    """Fully interactive visual designer - all direct manipulation."""

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle('🎨 Interactive Skin Designer')
        self.resize(1000, 700)

        self.video_controls = video_controls
        self.selected_element = None
        self.skin_data = self._get_default_skin_data()

        layout = QVBoxLayout(self)

        # Title
        title = QLabel("🎮 Drag to move • Drag corners to resize • Right-click for colors/fonts • Changes apply live!")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 10px; background: #1A1A1A;")
        layout.addWidget(title)

        # Canvas
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 900, 200)
        self.scene.setBackgroundBrush(QBrush(QColor("#0D0D0D")))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.view)

        # Build realistic mockup
        self._build_realistic_mockup()

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        load_btn = QPushButton("📁 Load Skin")
        load_btn.clicked.connect(self._load_skin)
        btn_layout.addWidget(load_btn)

        export_btn = QPushButton("💾 Export Skin")
        export_btn.clicked.connect(self._export_skin)
        btn_layout.addWidget(export_btn)

        apply_btn = QPushButton("✓ Apply & Close")
        apply_btn.setStyleSheet("background: #2196F3; color: white; padding: 8px 16px;")
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)

        layout.addLayout(btn_layout)

    def _get_default_skin_data(self):
        """Default skin structure."""
        return {
            'name': 'Custom Skin',
            'version': '1.0',
            'video_player': {
                'layout': {'control_bar_height': 60, 'button_spacing': 8, 'section_spacing': 20},
                'styling': {
                    'background': '#000000',
                    'control_bar_color': '#000000',
                    'control_bar_opacity': 0.80,
                    'button_size': 40,
                    'button_bg_color': '#2b2b2b',
                    'button_hover_color': '#3a3a3a',
                    'timeline_height': 8,
                    'timeline_color': '#2196F3',
                    'loop_marker_start_color': '#FF0080',
                    'loop_marker_end_color': '#FF8C00',
                },
                'borders': {'radius': 4},
                'shadows': {}
            }
        }

    def _build_realistic_mockup(self):
        """Build realistic-looking control mockup."""
        # Control bar background (semi-transparent black)
        control_bar = QGraphicsRectItem(0, 0, 900, 80)
        control_bar.setBrush(QBrush(QColor("#000000")))
        control_bar.setOpacity(0.8)
        self.scene.addItem(control_bar)

        # Top row: Buttons
        y_pos = 10
        button_size = 40
        x = 20

        # Playback buttons
        buttons = [
            ("▶", "Play"),
            ("■", "Stop"),
            ("🔇", "Mute"),
        ]

        self.elements = []
        for icon, name in buttons:
            btn = InteractiveElement(x, y_pos, button_size, button_size, "button", icon, self)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x += button_size + 8

        x += 12  # Section gap

        # Navigation buttons
        nav = [("<<", "Skip Back"), ("<", "Prev"), (">", "Next"), (">>", "Skip Fwd")]
        for icon, name in nav:
            btn = InteractiveElement(x, y_pos, button_size, button_size, "button", icon, self)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x += button_size + 8

        x += 12

        # Labels
        frame_label = InteractiveElement(x, y_pos + 10, 80, 20, "label", "Frame: 0", self)
        frame_label.label.setDefaultTextColor(QColor("#FFFFFF"))
        self.scene.addItem(frame_label)
        self.elements.append(frame_label)

        # Timeline slider (below buttons)
        timeline_y = 65
        timeline = InteractiveElement(20, timeline_y, 860, 8, "slider", "", self)
        timeline.setBrush(QBrush(QColor("#2196F3")))
        timeline.label.hide()  # No label for slider
        self.scene.addItem(timeline)
        self.elements.append(timeline)

        # Loop markers (visual only)
        start_marker = QGraphicsTextItem("▼")
        start_marker.setDefaultTextColor(QColor("#FF0080"))
        start_marker.setPos(150, timeline_y + 10)
        start_marker.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.scene.addItem(start_marker)

        end_marker = QGraphicsTextItem("▼")
        end_marker.setDefaultTextColor(QColor("#FF8C00"))
        end_marker.setPos(700, timeline_y + 10)
        end_marker.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.scene.addItem(end_marker)

    def element_selected(self, element):
        """Handle element selection."""
        self.selected_element = element

    def update_element_size(self, element, width, height):
        """Update skin data when element resized."""
        try:
            if element.element_type == "button":
                self.skin_data['video_player']['styling']['button_size'] = int(max(width, height))
            elif element.element_type == "slider":
                self.skin_data['video_player']['styling']['timeline_height'] = int(height)

            self._apply_live()
        except Exception as e:
            print(f"Error updating size: {e}")

    def update_element_color(self, element, color, opacity):
        """Update color in skin data."""
        try:
            if element.element_type == "button":
                self.skin_data['video_player']['styling']['button_bg_color'] = color.name()
            elif element.element_type == "slider":
                self.skin_data['video_player']['styling']['timeline_color'] = color.name()

            self._apply_live()
        except Exception as e:
            print(f"Error updating color: {e}")

    def update_element_opacity(self, element, opacity):
        """Update opacity."""
        try:
            if element.element_type == "button":
                # Could add button_opacity property
                pass
            self._apply_live()
        except Exception as e:
            print(f"Error updating opacity: {e}")

    def update_element_font(self, element, font):
        """Update font."""
        try:
            self.skin_data['video_player']['styling']['label_font_size'] = font.pointSize()
            self._apply_live()
        except Exception as e:
            print(f"Error updating font: {e}")

    def _apply_live(self):
        """Apply current skin live."""
        try:
            if self.video_controls:
                applier = SkinApplier(self.skin_data)
                self.video_controls.current_applier = applier
                self.video_controls.apply_current_skin()
        except Exception as e:
            print(f"Error applying skin live: {e}")
            import traceback
            traceback.print_exc()

    def _export_skin(self):
        """Export to YAML."""
        skins_dir = Path(__file__).parent.parent / 'skins' / 'user'
        skins_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Skin", str(skins_dir / "custom.yaml"), "YAML (*.yaml)"
        )

        if file_path:
            try:
                with open(file_path, 'w') as f:
                    yaml.dump(self.skin_data, f, default_flow_style=False)
                QMessageBox.information(self, "Exported", f"Saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _load_skin(self):
        """Load skin from file."""
        skins_dir = Path(__file__).parent.parent / 'skins'
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Skin", str(skins_dir), "YAML (*.yaml)"
        )

        if file_path:
            try:
                with open(file_path) as f:
                    self.skin_data = yaml.safe_load(f)
                self._apply_live()
                QMessageBox.information(self, "Loaded", "Skin loaded successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
