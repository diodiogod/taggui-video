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

    def __init__(self, x, y, w, h, element_type, label_text, designer, property_name=None):
        super().__init__(0, 0, w, h)
        self.element_type = element_type
        self.label_text = label_text
        self.property_name = property_name or label_text  # For tooltip and saving
        self.designer = designer
        self.bg_color = QColor("#2b2b2b")
        self.hover_color = QColor("#3a3a3a")
        self.opacity_value = 1.0
        self._updating = False  # Prevent recursion during resize

        self.setPos(x, y)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Tooltip showing property name (1s delay is default)
        self.setToolTip(f"Property: {self.property_name}")

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
        """Handle selection and position changes."""
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

        elif change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            # Save position when moved
            if not self._updating:
                pos = self.pos()
                self.designer.update_element_position(self, pos.x(), pos.y())

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
        from PySide6.QtWidgets import QMenu, QWidgetAction
        from PySide6.QtGui import QAction

        # Prevent menu on invalid events
        if not event or not event.screenPos():
            return

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: white;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #2196F3;
            }
        """)

        # Color picker action - opens QColorDialog directly
        color_action = QAction("🎨 Pick Color...", menu)
        color_action.triggered.connect(self._pick_color_direct)
        menu.addAction(color_action)

        # Opacity slider widget directly in menu
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(10, 5, 10, 5)

        opacity_label = QLabel("Opacity:")
        opacity_label.setStyleSheet("color: white;")
        opacity_layout.addWidget(opacity_label)

        opacity_slider = QSlider(Qt.Orientation.Horizontal)
        opacity_slider.setRange(0, 100)
        opacity_slider.setValue(int(self.opacity_value * 100))
        opacity_slider.setFixedWidth(150)
        opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        opacity_layout.addWidget(opacity_slider)

        opacity_value_label = QLabel(f"{int(self.opacity_value * 100)}%")
        opacity_value_label.setStyleSheet("color: white; min-width: 35px;")
        opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        opacity_slider.valueChanged.connect(lambda v: opacity_value_label.setText(f"{v}%"))
        opacity_layout.addWidget(opacity_value_label)

        opacity_action = QWidgetAction(menu)
        opacity_action.setDefaultWidget(opacity_widget)
        menu.addAction(opacity_action)

        # Font picker for labels AND text buttons (like LOOP, loop markers, etc.)
        if self.element_type in ["label", "button"]:
            menu.addSeparator()
            font_action = QAction("🔤 Change Font...", menu)
            font_action.triggered.connect(self._pick_font)
            menu.addAction(font_action)

        menu.exec(event.screenPos())
        event.accept()

    def _on_opacity_slider_changed(self, value):
        """Handle opacity slider change in context menu."""
        self.opacity_value = value / 100.0
        self.setOpacity(self.opacity_value)
        self.designer.update_element_color(self, self.bg_color, self.opacity_value)
        self.designer._apply_live()

    def _pick_color_direct(self):
        """Open color picker directly."""
        color = QColorDialog.getColor(self.bg_color, self.designer, "Pick Color")
        if color.isValid():
            self.bg_color = color
            self.setBrush(QBrush(color))
            self.designer.update_element_color(self, color, self.opacity_value)
            self.designer._apply_live()

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
        self.current_skin_name = None
        self.current_skin_path = None

        # Load current active skin from video_controls, or default
        if video_controls and hasattr(video_controls, 'skin_manager'):
            current_applier = video_controls.skin_manager.get_current_applier()
            if current_applier and current_applier.skin:
                self.skin_data = current_applier.skin.copy()
                self.current_skin_name = self.skin_data.get('name', 'Custom Skin')
                # Get the skin file path for saving
                skin_manager = video_controls.skin_manager
                if hasattr(skin_manager, 'current_skin_path') and skin_manager.current_skin_path:
                    self.current_skin_path = skin_manager.current_skin_path
            else:
                self.skin_data = self._get_default_skin_data()
        else:
            self.skin_data = self._get_default_skin_data()

        layout = QVBoxLayout(self)

        # Title
        title = QLabel("🎮 Drag to move • Drag corners to resize • Right-click for colors/fonts • Changes apply live!")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 10px; background: #1A1A1A;")
        layout.addWidget(title)

        # Canvas
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 900, 200)

        # Gradient background to show opacity changes
        from PySide6.QtGui import QLinearGradient
        gradient = QLinearGradient(0, 0, 900, 200)
        gradient.setColorAt(0.0, QColor("#1A1A1A"))
        gradient.setColorAt(0.5, QColor("#2D2D2D"))
        gradient.setColorAt(1.0, QColor("#1A1A1A"))
        self.scene.setBackgroundBrush(QBrush(gradient))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.view)

        # Build realistic mockup
        self._build_realistic_mockup()

        # Bottom buttons
        btn_layout = QHBoxLayout()

        # Left side - Reset button
        reset_btn = QPushButton("🔄 Reset to Default")
        reset_btn.clicked.connect(self._reset_to_default)
        btn_layout.addWidget(reset_btn)

        btn_layout.addStretch()

        # Right side - Load, Save, Export, Apply
        load_btn = QPushButton("📁 Load Skin...")
        load_btn.clicked.connect(self._load_skin)
        btn_layout.addWidget(load_btn)

        save_btn = QPushButton("💾 Save")
        save_btn.setToolTip("Save changes to current skin file")
        save_btn.clicked.connect(self._save_skin)
        btn_layout.addWidget(save_btn)

        export_btn = QPushButton("💾 Export As...")
        export_btn.setToolTip("Save as a new skin file")
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

    def _apply_element_font(self, element, styling):
        """Apply custom font to element if defined in skin."""
        font_family = styling.get(f'{element.property_name}_font_family', 'Arial')
        font_size = styling.get(f'{element.property_name}_font_size', 12)
        font_weight = styling.get(f'{element.property_name}_font_weight', 'normal')

        font = QFont(font_family, font_size)
        if font_weight == 'bold':
            font.setWeight(QFont.Weight.Bold)

        element.label.setFont(font)

    def _build_realistic_mockup(self):
        """Build realistic-looking control mockup matching exact video_controls.py 3-row layout."""
        styling = self.skin_data.get('video_player', {}).get('styling', {})
        layout_data = self.skin_data.get('video_player', {}).get('layout', {})
        positions = self.skin_data.get('designer_positions', {})

        control_bar_color = styling.get('control_bar_color', '#242424')
        control_bar_opacity = styling.get('control_bar_opacity', 0.95)
        button_size = styling.get('button_size', 40)
        button_bg_color = styling.get('button_bg_color', '#2b2b2b')
        button_spacing = layout_data.get('button_spacing', 8)
        section_spacing = layout_data.get('section_spacing', 20)
        timeline_color = styling.get('timeline_color', '#2196F3')
        timeline_bg_color = styling.get('timeline_bg_color', '#1A1A1A')
        timeline_height = styling.get('timeline_height', 8)
        loop_start_color = styling.get('loop_marker_start_color', '#FF0080')
        loop_end_color = styling.get('loop_marker_end_color', '#FF8C00')
        text_color = styling.get('text_color', '#FFFFFF')

        # Control bar background - INTERACTIVE
        self.control_bar = InteractiveElement(0, 0, 900, 140, "control_bar", "Background", self, "control_bar_color")
        self.control_bar.setBrush(QBrush(QColor(control_bar_color)))
        self.control_bar.setOpacity(control_bar_opacity)
        self.control_bar.bg_color = QColor(control_bar_color)
        self.control_bar.opacity_value = control_bar_opacity
        self.control_bar.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.control_bar.setZValue(-1)
        self.scene.addItem(self.control_bar)

        self.elements = [self.control_bar]

        # ROW 1: Playback controls + navigation + frame controls + speed slider
        y_row1 = 10
        x = 20

        # Playback buttons
        for icon, display_name, prop_name in [("▶", "Play", "play_button"), ("■", "Stop", "stop_button"), ("🔇", "Mute", "mute_button")]:
            saved_pos = positions.get(prop_name, {})
            btn_x = saved_pos.get('x', x)
            btn_y = saved_pos.get('y', y_row1)
            btn_color = styling.get(f"{prop_name}_color", button_bg_color)
            btn_opacity = styling.get(f"{prop_name}_opacity", 1.0)

            btn = InteractiveElement(btn_x, btn_y, button_size, button_size, "button", icon, self, prop_name)
            btn.setBrush(QBrush(QColor(btn_color)))
            btn.setOpacity(btn_opacity)
            btn.bg_color = QColor(btn_color)
            btn.opacity_value = btn_opacity
            self._apply_element_font(btn, styling)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x += button_size + button_spacing

        x += section_spacing

        # Navigation/skip buttons
        for icon, display_name, prop_name in [("<<", "Skip Back", "skip_back_button"), ("<", "Prev", "prev_frame_button"),
                                                (">", "Next", "next_frame_button"), (">>", "Skip Fwd", "skip_forward_button")]:
            saved_pos = positions.get(prop_name, {})
            btn_x = saved_pos.get('x', x)
            btn_y = saved_pos.get('y', y_row1)
            btn_color = styling.get(f"{prop_name}_color", button_bg_color)
            btn_opacity = styling.get(f"{prop_name}_opacity", 1.0)

            btn = InteractiveElement(btn_x, btn_y, button_size, button_size, "button", icon, self, prop_name)
            btn.setBrush(QBrush(QColor(btn_color)))
            btn.setOpacity(btn_opacity)
            btn.bg_color = QColor(btn_color)
            btn.opacity_value = btn_opacity
            self._apply_element_font(btn, styling)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x += button_size + button_spacing

        x += section_spacing

        # Frame label + spinbox (combined as one element)
        saved_pos = positions.get('frame_label', {})
        label_x = saved_pos.get('x', x)
        label_y = saved_pos.get('y', y_row1 + 10)
        frame_label = InteractiveElement(label_x, label_y, 120, 20, "label", "Frame: 0 / 0", self, "frame_label")
        frame_label.label.setDefaultTextColor(QColor(text_color))
        self._apply_element_font(frame_label, styling)
        self.scene.addItem(frame_label)
        self.elements.append(frame_label)
        x += 120 + section_spacing

        # Speed slider (stretched to fill remaining space)
        saved_pos = positions.get('speed_slider', {})
        slider_x = saved_pos.get('x', x)
        slider_y = saved_pos.get('y', y_row1 + 15)
        speed_slider = InteractiveElement(slider_x, slider_y, 200, 10, "slider", "Speed", self, "speed_slider")
        speed_slider.setBrush(QBrush(QColor("#6B8E23")))  # Green gradient mid-tone
        speed_slider.label.setPos(slider_x + 210, slider_y - 5)
        speed_slider.label.setPlainText("1.00x")
        speed_slider.label.setDefaultTextColor(QColor("#32CD32"))
        self.scene.addItem(speed_slider)
        self.elements.append(speed_slider)

        # ROW 2: Timeline slider with loop markers
        y_row2 = 65
        timeline_width = 860

        # Timeline background track
        saved_pos = positions.get('timeline_bg', {})
        track_x = saved_pos.get('x', 20)
        track_y = saved_pos.get('y', y_row2)
        self.timeline_bg = InteractiveElement(track_x, track_y, timeline_width, timeline_height, "timeline_bg", "Track", self, "timeline_bg_color")
        self.timeline_bg.setBrush(QBrush(QColor(timeline_bg_color)))
        self.timeline_bg.label.hide()
        self.timeline_bg.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.scene.addItem(self.timeline_bg)
        self.elements.append(self.timeline_bg)

        # Timeline progress bar
        saved_pos = positions.get('timeline', {})
        timeline_x = saved_pos.get('x', 20)
        timeline_y_pos = saved_pos.get('y', y_row2)
        self.timeline = InteractiveElement(timeline_x, timeline_y_pos, timeline_width, timeline_height, "slider", "Progress", self, "timeline_color")
        self.timeline.setBrush(QBrush(QColor(timeline_color)))
        self.timeline.label.hide()
        self.timeline.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.scene.addItem(self.timeline)
        self.elements.append(self.timeline)

        # Loop markers (above timeline)
        self.start_marker = QGraphicsTextItem("▼")
        self.start_marker.setDefaultTextColor(QColor(loop_start_color))
        self.start_marker.setPos(150, y_row2 - 18)
        self.start_marker.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.scene.addItem(self.start_marker)

        self.end_marker = QGraphicsTextItem("▼")
        self.end_marker.setDefaultTextColor(QColor(loop_end_color))
        self.end_marker.setPos(700, y_row2 - 18)
        self.end_marker.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.scene.addItem(self.end_marker)

        # ROW 3: Info labels (left) + loop controls (right)
        y_row3 = 90
        x = 20

        # Time label
        saved_pos = positions.get('time_label', {})
        label_x = saved_pos.get('x', x)
        label_y = saved_pos.get('y', y_row3)
        time_label = InteractiveElement(label_x, label_y, 150, 20, "label", "00:00.000 / 00:00.000", self, "time_label")
        time_label.label.setDefaultTextColor(QColor(text_color))
        self._apply_element_font(time_label, styling)
        self.scene.addItem(time_label)
        self.elements.append(time_label)
        x += 150 + 10

        # FPS label
        saved_pos = positions.get('fps_label', {})
        label_x = saved_pos.get('x', x)
        label_y = saved_pos.get('y', y_row3)
        fps_label = InteractiveElement(label_x, label_y, 80, 20, "label", "0.00 fps", self, "fps_label")
        fps_label.label.setDefaultTextColor(QColor(text_color))
        self._apply_element_font(fps_label, styling)
        self.scene.addItem(fps_label)
        self.elements.append(fps_label)
        x += 80 + 10

        # Frame count label
        saved_pos = positions.get('frame_count_label', {})
        label_x = saved_pos.get('x', x)
        label_y = saved_pos.get('y', y_row3)
        frame_count_label = InteractiveElement(label_x, label_y, 80, 20, "label", "0 frames", self, "frame_count_label")
        frame_count_label.label.setDefaultTextColor(QColor(text_color))
        self._apply_element_font(frame_count_label, styling)
        self.scene.addItem(frame_count_label)
        self.elements.append(frame_count_label)

        # Loop controls (right side of row 3)
        x = 620  # Right side positioning

        # Loop buttons
        for icon, display_name, prop_name in [("◀", "Loop Start", "loop_start_button"),
                                                ("▶", "Loop End", "loop_end_button"),
                                                ("✕", "Loop Reset", "loop_reset_button")]:
            saved_pos = positions.get(prop_name, {})
            btn_x = saved_pos.get('x', x)
            btn_y = saved_pos.get('y', y_row3 - 5)
            btn_color = styling.get(f"{prop_name}_color", button_bg_color)
            btn_opacity = styling.get(f"{prop_name}_opacity", 1.0)

            btn = InteractiveElement(btn_x, btn_y, 30, 30, "button", icon, self, prop_name)
            btn.setBrush(QBrush(QColor(btn_color)))
            btn.setOpacity(btn_opacity)
            btn.bg_color = QColor(btn_color)
            btn.opacity_value = btn_opacity
            self._apply_element_font(btn, styling)
            self.scene.addItem(btn)
            self.elements.append(btn)
            x += 30 + button_spacing

        # Loop checkbox
        saved_pos = positions.get('loop_checkbox', {})
        chk_x = saved_pos.get('x', x)
        chk_y = saved_pos.get('y', y_row3 - 5)
        btn_color = styling.get("loop_checkbox_color", button_bg_color)
        btn_opacity = styling.get("loop_checkbox_opacity", 1.0)

        loop_chk = InteractiveElement(chk_x, chk_y, 50, 30, "button", "LOOP", self, "loop_checkbox")
        loop_chk.setBrush(QBrush(QColor(btn_color)))
        loop_chk.setOpacity(btn_opacity)
        loop_chk.bg_color = QColor(btn_color)
        loop_chk.opacity_value = btn_opacity
        self._apply_element_font(loop_chk, styling)
        self.scene.addItem(loop_chk)
        self.elements.append(loop_chk)

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

    def update_element_position(self, element, x, y):
        """Update skin data when element moved."""
        try:
            # Store positions in a custom section of skin data
            if 'designer_positions' not in self.skin_data:
                self.skin_data['designer_positions'] = {}

            self.skin_data['designer_positions'][element.property_name] = {
                'x': int(x),
                'y': int(y)
            }
            # Don't apply live for position changes (just save for next load)
        except Exception as e:
            print(f"Error updating position: {e}")

    def update_element_color(self, element, color, opacity):
        """Update color in skin data and visual mockup."""
        try:
            if element.element_type == "button":
                # Save color for this specific button using its property_name
                button_color_key = f"{element.property_name}_color"
                self.skin_data['video_player']['styling'][button_color_key] = color.name()

                # Also save opacity if specified
                if opacity is not None:
                    button_opacity_key = f"{element.property_name}_opacity"
                    self.skin_data['video_player']['styling'][button_opacity_key] = opacity

                # Update this button in mockup
                element.setBrush(QBrush(color))
                if opacity is not None:
                    element.setOpacity(opacity)

            elif element.element_type == "slider":
                # Use property_name to determine which slider property to update
                color_key = f"{element.property_name}_color"
                self.skin_data['video_player']['styling'][color_key] = color.name()
                # Update element in mockup
                element.setBrush(QBrush(color))

            elif element.element_type == "timeline_bg":
                self.skin_data['video_player']['styling']['timeline_bg_color'] = color.name()
                # Update timeline background in mockup
                if hasattr(self, 'timeline_bg'):
                    self.timeline_bg.setBrush(QBrush(color))

            elif element.element_type == "control_bar":
                self.skin_data['video_player']['styling']['control_bar_color'] = color.name()
                # Update control bar in mockup
                if hasattr(self, 'control_bar'):
                    self.control_bar.setBrush(QBrush(color))

            # Update opacity for control bar or any element that has it
            if opacity is not None and element.element_type == "control_bar":
                self.skin_data['video_player']['styling']['control_bar_opacity'] = opacity
                if hasattr(self, 'control_bar'):
                    self.control_bar.setOpacity(opacity)

            self._apply_live()
        except Exception as e:
            print(f"Error updating color: {e}")

    def update_element_opacity(self, element, opacity):
        """Update opacity in skin data and visual mockup."""
        try:
            # Update control bar opacity
            self.skin_data['video_player']['styling']['control_bar_opacity'] = opacity
            if hasattr(self, 'control_bar_rect'):
                self.control_bar_rect.setOpacity(opacity)

            self._apply_live()
        except Exception as e:
            print(f"Error updating opacity: {e}")

    def update_element_font(self, element, font):
        """Update font with per-element settings."""
        try:
            # Save font properties specific to this element
            font_family_key = f"{element.property_name}_font_family"
            font_size_key = f"{element.property_name}_font_size"
            font_weight_key = f"{element.property_name}_font_weight"

            self.skin_data['video_player']['styling'][font_family_key] = font.family()
            self.skin_data['video_player']['styling'][font_size_key] = font.pointSize()

            # Save weight as 'bold' or 'normal'
            if font.weight() >= QFont.Weight.Bold.value:
                self.skin_data['video_player']['styling'][font_weight_key] = 'bold'
            else:
                self.skin_data['video_player']['styling'][font_weight_key] = 'normal'

            # Update the visual element
            element.label.setFont(font)
            element._center_label()

            self._apply_live()
        except Exception as e:
            print(f"Error updating font: {e}")
            import traceback
            traceback.print_exc()

    def _apply_live(self):
        """Apply current skin live to video controls."""
        try:
            if self.video_controls and hasattr(self.video_controls, 'skin_manager'):
                # Update skin manager with new data
                self.video_controls.skin_manager.current_skin = self.skin_data
                self.video_controls.skin_manager.current_applier = SkinApplier(self.skin_data)
                # Apply to video controls
                self.video_controls.apply_current_skin()
        except Exception as e:
            print(f"Error applying skin live: {e}")
            import traceback
            traceback.print_exc()

    def _save_skin(self):
        """Save changes to current skin file."""
        if not self.current_skin_path:
            # No current file, ask user to export instead
            reply = QMessageBox.question(
                self, "Save As New?",
                "No skin file is currently loaded. Would you like to export as a new skin?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._export_skin()
            return

        # Check if it's a default skin (read-only)
        if 'defaults' in str(self.current_skin_path):
            QMessageBox.warning(
                self, "Cannot Save",
                "Default skins are read-only. Use 'Export As...' to save as a new custom skin."
            )
            return

        # Save to current file
        try:
            with open(self.current_skin_path, 'w') as f:
                yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)

            # Refresh skin manager and reload
            if self.video_controls and hasattr(self.video_controls, 'skin_manager'):
                self.video_controls.skin_manager.refresh_available_skins()
                skin_name = self.skin_data.get('name', 'Custom Skin')
                self.video_controls.switch_skin(skin_name)
                # Refresh context menu
                self._refresh_context_menu()

            QMessageBox.information(self, "Saved", f"Skin updated:\n{self.current_skin_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def _export_skin(self):
        """Export as new skin file."""
        skins_dir = Path(__file__).parent.parent / 'skins' / 'user'
        skins_dir.mkdir(parents=True, exist_ok=True)

        default_name = self.skin_data.get('name', 'Custom Skin').lower().replace(' ', '-') + '.yaml'
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export As New Skin", str(skins_dir / default_name), "YAML (*.yaml)"
        )

        if file_path:
            try:
                with open(file_path, 'w') as f:
                    yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)

                # Update current path to new file
                self.current_skin_path = Path(file_path)

                # Refresh skin manager and switch to new skin
                if self.video_controls and hasattr(self.video_controls, 'skin_manager'):
                    self.video_controls.skin_manager.refresh_available_skins()
                    skin_name = self.skin_data.get('name', 'Custom Skin')
                    self.video_controls.switch_skin(skin_name)
                    # Refresh context menu
                    self._refresh_context_menu()

                QMessageBox.information(self, "Exported", f"Saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _reset_to_default(self):
        """Reset to default skin values."""
        reply = QMessageBox.question(
            self, "Reset to Default?",
            "This will reset all values to the default Classic skin. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.skin_data = self._get_default_skin_data()
            self.current_skin_name = self.skin_data.get('name', 'Custom Skin')
            self.current_skin_path = None

            # Rebuild mockup with default values
            self._rebuild_mockup()

            self._apply_live()
            QMessageBox.information(self, "Reset", "Skin reset to default values")

    def _refresh_context_menu(self):
        """Refresh video controls context menu with updated skins."""
        # Context menu is rebuilt each time it's shown, so just ensure skin_manager is refreshed
        # (already done in _save_skin and _export_skin via refresh_available_skins)

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
                self.current_skin_path = Path(file_path)
                self.current_skin_name = self.skin_data.get('name', 'Custom Skin')

                # Rebuild mockup with new skin values
                self._rebuild_mockup()

                self._apply_live()
                QMessageBox.information(self, "Loaded", f"Skin loaded: {self.current_skin_name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _rebuild_mockup(self):
        """Rebuild the visual mockup with current skin values."""
        # Clear existing elements
        for item in self.scene.items():
            self.scene.removeItem(item)

        # Rebuild with current skin data
        self._build_realistic_mockup()
