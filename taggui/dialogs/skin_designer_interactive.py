"""Fully Interactive Skin Designer - Pure visual editing, no settings panels."""

from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsItem,
    QColorDialog, QFileDialog, QMessageBox, QLabel,
    QSlider, QFontDialog, QWidget, QGridLayout, QSpinBox,
    QButtonGroup
)
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QFont, QIcon, QAction, QPixmap
import yaml

from skins.engine import SkinApplier
from widgets.video_controls import LoopSlider, SpeedSlider


class ResizeHandle(QGraphicsEllipseItem):
    """Corner handle for resizing elements."""

    def __init__(self, parent_element):
        super().__init__(-6, -6, 12, 12, parent_element)
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


class SelectionFrame(QGraphicsRectItem):
    """Visual frame indicating selection."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.setPen(QPen(QColor("#2196F3"), 2, Qt.PenStyle.DashLine))
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.hide()


class InteractiveElement(QGraphicsProxyWidget):
    """Fully interactive UI element - wraps real widget, adds drag/resize."""

    def __init__(self, widget, x, y, w, h, element_type, prop_name, designer):
        super().__init__()
        self.setWidget(widget)
        self.widget = widget
        self.element_type = element_type
        self.property_name = prop_name
        self.designer = designer
        self._updating = False

        self.setPos(x, y)
        self.setMinimumSize(w, h)
        
        # Selection frame
        self.selection_frame = SelectionFrame(self)
        self.selection_frame.setRect(0, 0, w, h)
        
        # Resize handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()
        
        self.resize(w, h)
        
        # Flags
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        # Tooltip
        self.setToolTip(f"Property: {self.property_name}")

        # Block mouse events to inner widget to allow dragging
        # We set this to True so the proxy widget receives the events for selection/moving
        # instead of the button/slider interpreting them as clicks.
        self.widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setMinimumSize(self, w, h):
        self.widget.setMinimumSize(w, h)
        self.widget.resize(w, h)

    def resize(self, w, h):
        self.widget.resize(w, h) # Resize underlying widget
        self.selection_frame.setRect(0, 0, w, h)
        self.resize_handle.setPos(w, h)
        super().resize(w, h) # Resize proxy

    def resize_to_point(self, point):
        """Resize element to given point (in local coordinates)."""
        if self._updating:
            return

        self._updating = True
        
        new_width = max(20, point.x())
        new_height = max(20, point.y())
        
        self.resize(new_width, new_height)
        
        # Update skin data
        self.designer.update_element_size(self, new_width, new_height)
        
        self._updating = False

    def itemChange(self, change, value):
        """Handle selection and position changes."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.isSelected():
                self.selection_frame.show()
                self.resize_handle.show()
                self.designer.element_selected(self)
            else:
                self.selection_frame.hide()
                self.resize_handle.hide()

        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if not self._updating:
                pos = self.pos()
                self.designer.update_element_position(self, pos.x(), pos.y())

        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Force QGraphicsItem behavior (selection/moving) instead of Proxy forwarding."""
        # By calling QGraphicsItem.mousePressEvent directly, we bypass QGraphicsProxyWidget's
        # logic that tries to send the event to the embedded widget.
        # This ensures the item is selected and ready to move, and the button doesn't 'click'.
        return QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        """Force QGraphicsItem behavior."""
        # If moving manually, we should clear strict alignment state
        super().mouseMoveEvent(event) # Call QGraphicsItem.mouseMoveEvent through super or direct
        # But wait, QGraphicsItem.mouseMoveEvent (which we called) updates position.
        # We need to notify designer.
        if self.designer and self.isSelected():
             self.designer.clear_element_alignment(self)
        return QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        """Force QGraphicsItem behavior."""
        return QGraphicsItem.mouseReleaseEvent(self, event)

    def contextMenuEvent(self, event):
        """Right-click for options."""
        menu = self.designer.create_context_menu(self)
        menu.exec(event.screenPos())
        event.accept()
        
    def paint(self, painter, option, widget):
        # QGraphicsProxyWidget paints the widget automatically. 
        super().paint(painter, option, widget)


from .properties_panel import PropertiesPanel

# ... imports ...

class SkinDesignerInteractive(QDialog):
    """Fully interactive visual designer - 1:1 Match with Real Player."""

    def __init__(self, parent=None, video_controls=None):
        super().__init__(parent)
        self.setWindowTitle('🎨 Interactive Skin Designer (1:1 Fidelity)')
        self.resize(1300, 800) # Wider to accommodate panel

        self.video_controls = video_controls
        self.selected_element = None
        
        # Initialize default skin data
        if video_controls and hasattr(video_controls, 'skin_manager') and video_controls.skin_manager.current_skin:
             self.skin_data = video_controls.skin_manager.current_skin.copy()
        else:
             self.skin_data = self._get_default_skin_data()
            
        # UI Layout
        main_layout = QHBoxLayout(self)
        
        # Center Area (Toolbar + Canvas + Buttons)
        center_layout = QVBoxLayout()
        
        # 1. Alignment Toolbar
        toolbar_layout = self._create_alignment_toolbar()
        center_layout.addLayout(toolbar_layout)
        
        # 2. Info Bar
        info_label = QLabel("🎯 Drag elements to position • Resize with corner handle • Right-click for options")
        info_label.setStyleSheet("color: #aaa; font-weight: bold; margin-bottom: 5px;")
        center_layout.addWidget(info_label)

        # 3. Graphics Scene
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 900, 300)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        # Create a checkerboard background for transparency
        check_size = 20
        grid_pixmap = QPixmap(check_size * 2, check_size * 2)
        grid_pixmap.fill(QColor("#333333")) # Darker square
        painter = QPainter(grid_pixmap)
        painter.fillRect(0, 0, check_size, check_size, QColor("#444444")) # Lighter square
        painter.fillRect(check_size, check_size, check_size, check_size, QColor("#444444"))
        painter.end()
        self.view.setBackgroundBrush(QBrush(grid_pixmap))
        
        center_layout.addWidget(self.view)
        
        # 4. Bottom Buttons
        btn_layout = QHBoxLayout()
        
        apply_btn = QPushButton("▶ Apply to Player")
        apply_btn.clicked.connect(self._apply_skin)
        btn_layout.addWidget(apply_btn)
        
        save_btn = QPushButton("💾 Save Skin")
        save_btn.clicked.connect(self._save_skin)
        btn_layout.addWidget(save_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(close_btn)
        center_layout.addLayout(btn_layout)
        
        main_layout.addLayout(center_layout, stretch=1)
        
        # Right Panel (Properties)
        self.properties_panel = PropertiesPanel(self)
        self.properties_panel.setFixedWidth(280)
        main_layout.addWidget(self.properties_panel)
        
        # Build the mockups
        self._build_realistic_mockup()

    def _create_alignment_toolbar(self):
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # Helper to create buttons
        def add_btn(text, callback, tooltip):
            btn = QPushButton(text)
            btn.setFixedWidth(40)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
            
        # Icons (using system theme or simple text fallback)
        actions = [
            ("Align Left", "format-justify-left", 'left', "Align Selection to Container Left"),
            ("Align Center", "format-justify-center", 'h_center', "Align Selection to Container Center"),
            ("Align Right", "format-justify-right", 'right', "Align Selection to Container Right"),
            ("|", None, None, None), # Separator
            ("Align Top", "format-justify-fill", 'top', "Align Selection to Container Top"), 
            ("Align Middle", "format-justify-center", 'v_center', "Align Selection to Container Middle"),
            ("Align Bottom", "format-justify-fill", 'bottom', "Align Selection to Container Bottom"),
        ]
        
        self.align_btns = {}
        alignment_group = QButtonGroup(self) # Exclusive check? No, H and V are independent.
        # Actually, H and V are independent. We can have separate groups or just manage manually.
        
        for text, icon_name, align_type, tooltip in actions:
            if text == "|":
                layout.addSpacing(10)
                continue
            
            btn = QPushButton()
            icon = QIcon.fromTheme(icon_name) if icon_name else QIcon()
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setText("")
            else:
                btn.setText(text)
            
            btn.setFixedWidth(40)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            
            # Use closure to capture align_type
            btn.clicked.connect(lambda checked, t=align_type: self._align_items(t))
            
            layout.addWidget(btn)
            self.align_btns[align_type] = btn
            alignment_group.addButton(btn) # Make exclusive
        
        layout.addStretch()
        return layout
        
        layout.addStretch()
        return layout

    def _align_items(self, mode):
        items = self.scene.selectedItems()
        if len(items) < 2:
            return # Need 2+ items to align (or align to canvas? stick to items for now)
            
        # Sort items? Typically align to the first selected or the one with extreme coordinate
        # Let's align to the 'anchor' item (usually the one with the most extreme value in that direction)
        
        if mode == 'left':
            anchor_x = min(item.pos().x() for item in items)
            for item in items:
                item.setPos(anchor_x, item.pos().y())
        elif mode == 'right':
            anchor_x = max(item.pos().x() + item.boundingRect().width() for item in items)
            for item in items:
                item.setPos(anchor_x - item.boundingRect().width(), item.pos().y())
        elif mode == 'h_center':
            # Align centers
            centers = [item.pos().x() + item.boundingRect().width()/2 for item in items]
            avg_center = sum(centers) / len(centers) # Average center? Or center of bounding box?
            # Let's use average center for now
            for item in items:
                 new_x = avg_center - item.boundingRect().width()/2
                 item.setPos(new_x, item.pos().y())
        elif mode == 'top':
            anchor_y = min(item.pos().y() for item in items)
            for item in items:
                item.setPos(item.pos().x(), anchor_y)
        elif mode == 'bottom':
            # Note: InteractiveElement uses widget geometry. QGraphicsProxyWidget boundingRect usually matches widget.
            anchor_y = max(item.pos().y() + item.boundingRect().height() for item in items)
            for item in items:
                item.setPos(item.pos().x(), anchor_y - item.boundingRect().height())
        elif mode == 'v_center':
             centers = [item.pos().y() + item.boundingRect().height()/2 for item in items]
             avg_center = sum(centers) / len(centers)
             for item in items:
                 new_y = avg_center - item.boundingRect().height()/2
                 item.setPos(item.pos().x(), new_y)

    def _on_selection_changed(self):
        """Handle selection change."""
        items = self.scene.selectedItems()
        if items:
            self.selected_item = items[0]
            self.properties_panel.set_element(self.selected_item)
            
            # Update alignment buttons state
            align_state = None
            if 'designer_positions' in self.skin_data:
                positions = self.skin_data['designer_positions']
                # Ensure we look up using the correct key
                prop_name = self.selected_item.property_name
                if prop_name in positions:
                    align_state = positions[prop_name].get('align')
            
            self._update_alignment_toolbar_state(align_state)
            
        else:
            self.selected_item = None
            self.properties_panel.set_element(None)
            self._update_alignment_toolbar_state(None)

    def element_selected(self, element):
        # Called by element itself on click
        # The scene selection check handles most logic, but this can ensure sync
        pass


    def _get_default_skin_data(self):
        # ... (Same as before, abbreviated for now) ...
        return {
            'name': 'Custom Skin',
            'version': '1.0',
            'video_player': {
                'layout': {'control_bar_height': 60, 'button_spacing': 8},
                'styling': {'background': '#000000', 'control_bar_opacity': 0.8}
            }
        }

    def _build_realistic_mockup(self):
        """Builds the scene using REAL widgets via QGraphicsProxyWidget."""
        self.scene.clear()
        
        # Grid Background (Custom draw in drawBackground of view? Or item?)
        # For now, let's keep the dark gray background but maybe add a grid later.
        
        # Create a temporary applier for this skin data
        applier = SkinApplier(self.skin_data)
        
        # --- 1. Control Bar Background ---
        layout_data = self.skin_data.get('video_player', {}).get('layout', {})
        h_control = layout_data.get('control_bar_height', 160) 
        if h_control < 150: h_control = 160 # Enforce height for new layout
        w_control = 900
        
        bg_widget = QWidget()
        bg_widget.setObjectName("control_bar_bg")
        # Apply style manually or via applier if adapted
        styling = self.skin_data.get('video_player', {}).get('styling', {})
        bg_color = styling.get('control_bar_color', '#101010')
        bg_widget.setStyleSheet(f"background-color: {bg_color}; border-radius: 8px;")
        
        bg_proxy = InteractiveElement(bg_widget, 0, 0, w_control, h_control, "control_bar", "background", self)
        bg_proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False) 
        bg_proxy.setZValue(-10)
        self.scene.addItem(bg_proxy)
        
        positions = self.skin_data.get('designer_positions', {})
        
        # --- Helper to add widget ---
        def add_widget(widget, name, x, y, w, h, w_type="button"):
            # Apply skin style
            if w_type == 'button':
                applier.apply_to_button(widget)
            elif w_type == 'label':
                applier.apply_to_label(widget)
            
            # Get saved pos or default
            pos = positions.get(name, {'x': x, 'y': y})
            
            # For resize-ability, use saved size if available (todo)
            
            proxy = InteractiveElement(widget, pos['x'], pos['y'], w, h, w_type, name, self)
            self.scene.addItem(proxy)
            return proxy

        # --- Row 1: Playback Controls ---
        y_row1 = 20
        x_cursor = 20
        btn_size = 40
        spacing = 10
        
        # Play/Pause
        play_btn = QPushButton()
        play_btn.setIcon(QIcon.fromTheme('media-playback-start'))
        if play_btn.icon().isNull(): play_btn.setText("▶") # Fallback
        add_widget(play_btn, 'play_button', x_cursor, y_row1, btn_size, btn_size)
        x_cursor += btn_size + spacing
        
        # Stop
        stop_btn = QPushButton()
        stop_btn.setIcon(QIcon.fromTheme('media-playback-stop'))
        if stop_btn.icon().isNull(): stop_btn.setText("■")
        add_widget(stop_btn, 'stop_button', x_cursor, y_row1, btn_size, btn_size)
        x_cursor += btn_size + spacing
        
        # Mute
        mute_btn = QPushButton("🔇")
        add_widget(mute_btn, 'mute_button', x_cursor, y_row1, btn_size, btn_size)
        x_cursor += btn_size + spacing * 2
        
        # Skips & Frames
        skip_btns = [
             ('skip_back_button', '<<'),
             ('prev_frame_button', '<'), 
             ('next_frame_button', '>'), 
             ('skip_forward_button', '>>')
        ]
        
        for name, label in skip_btns:
            btn = QPushButton(label) # Use text for these as per video_controls (some used icons, some text)
            # Actually video_controls uses icons for prev/next and text for skip
            if 'frame' in name:
                icon_name = 'media-skip-backward' if 'prev' in name else 'media-skip-forward'
                btn.setIcon(QIcon.fromTheme(icon_name))
                if btn.icon().isNull(): btn.setText(label)
                else: btn.setText("")
            
            add_widget(btn, name, x_cursor, y_row1, btn_size, btn_size)
            x_cursor += btn_size + spacing

        x_cursor += spacing
        
        # Frame Counter (Label+Spinbox combo? Designer usually treats them as one block or separate?)
        # Let's add them as separate resizeable items
        frame_lbl = QLabel("Frame:")
        add_widget(frame_lbl, 'frame_label', x_cursor, y_row1+10, 50, 20, 'label')
        x_cursor += 50
        
        frame_spin = QSpinBox() # Just visual
        frame_spin.setValue(100)
        frame_spin.setStyleSheet("background: #333; color: white;")
        img_proxy = InteractiveElement(frame_spin, x_cursor, y_row1, 80, 25, "spinbox", "frame_spinbox", self)
        self.scene.addItem(img_proxy)
        x_cursor += 90
        
        # Speed
        speed_lbl = QLabel("Speed:")
        add_widget(speed_lbl, 'speed_label', x_cursor, y_row1+10, 50, 20, 'label')
        x_cursor += 50
        
        speed_val = QLabel("1.00x")
        speed_val.setStyleSheet("color: #4CAF50; font-weight: bold;")
        add_widget(speed_val, 'speed_value_label', x_cursor, y_row1+10, 50, 20, 'label')
        x_cursor += 60
        
        # Speed Slider
        speed = SpeedSlider(Qt.Orientation.Horizontal)
        speed.setMinimum(-200)
        speed.setMaximum(600)
        speed.setValue(100)
        applier.apply_to_speed_slider(speed)
        # Position it
        s_pos = positions.get('speed_slider', {'x': x_cursor, 'y': y_row1+5})
        s_proxy = InteractiveElement(speed, s_pos['x'], s_pos['y'], 150, 30, "slider", "speed_slider", self)
        self.scene.addItem(s_proxy)

        # --- Row 2: Timeline ---
        y_row2 = 70
        timeline = LoopSlider(Qt.Orientation.Horizontal)
        timeline.set_loop_markers(20, 80) 
        applier.apply_to_timeline_slider(timeline)
        timeline.setMinimum(0)
        timeline.setMaximum(100)
        timeline.setValue(50)
        
        t_pos = positions.get('timeline', {'x': 20, 'y': y_row2})
        t_proxy = InteractiveElement(timeline, t_pos['x'], t_pos['y'], 860, 30, "slider", "timeline", self)
        self.scene.addItem(t_proxy)
        
        # --- Row 3: Bottom Info & Loop Controls ---
        y_row3 = 110
        x_cursor = 20
        
        # Time / FPS
        time_lbl = QLabel("00:00.000 / 01:23.456")
        add_widget(time_lbl, 'time_label', x_cursor, y_row3, 150, 20, 'label')
        x_cursor += 160
        
        fps_lbl = QLabel("60.00 fps")
        add_widget(fps_lbl, 'fps_label', x_cursor, y_row3, 80, 20, 'label')
        x_cursor += 90
        
        # Loop Buttons
        x_loop = 650
        loop_reset = QPushButton("✕")
        add_widget(loop_reset, 'loop_reset_button', x_loop, y_row3, 30, 30)
        x_loop += 35
        
        loop_in = QPushButton("◀")
        add_widget(loop_in, 'loop_start_button', x_loop, y_row3, 30, 30)
        x_loop += 35
        
        loop_out = QPushButton("▶")
        add_widget(loop_out, 'loop_end_button', x_loop, y_row3, 30, 30)
        x_loop += 35
        
        loop_chk = QPushButton("LOOP")
        loop_chk.setCheckable(True)
        loop_chk.setChecked(True)
        # Manually apply style from video_controls prompt logic if applier doesn't handle checks well?
        # Applier likely handles 'button' generic.
        add_widget(loop_chk, 'loop_checkbox', x_loop, y_row3, 50, 30)

    def update_element_position(self, element, x, y):
        """Update element position in skin data."""
        if 'designer_positions' not in self.skin_data:
            self.skin_data['designer_positions'] = {}
        
        self.skin_data['designer_positions'][element.property_name] = {'x': int(x), 'y': int(y)}

    def update_element_size(self, element, w, h):
        """Update element size (if applicable)."""
        # For now, we mainly resized via styling for buttons, but if we support arbitrary resizing:
        # We might want to update 'button_size' globally if it's a button, or just this one?
        # For 1:1, usually buttons are uniform.
        # But for 'designer_positions', we could store size overrides too?
        # Let's just pass for now to avoid crash, or implement basic size override storage
        pass
    def update_element_color(self, element, color):
        """Update element color and refresh visual."""
        # Update skin data based on element type
        prop_name = element.property_name
        styling = self.skin_data['video_player']['styling']
        
        if element.element_type == 'button':
            key = f"{prop_name}_color" # e.g. play_button_color
            styling[key] = color.name()
            # Also update base button color if it's a generic button? No, specific override.
            
        elif element.element_type == 'slider':
            if prop_name == 'timeline':
                styling['timeline_color'] = color.name()
            elif prop_name == 'speed_slider':
                # speed slider uses gradient, maybe just update one stop or handle separately?
                # For now, let's say it updates the middle color
                styling['speed_gradient_mid'] = color.name()
                
        elif element.element_type == 'label':
             if prop_name == 'time_label':
                 styling['text_color'] = color.name()
        
        elif element.element_type == 'control_bar':
            styling['control_bar_color'] = color.name()
            
        # Re-apply style to this specific widget
        applier = SkinApplier(self.skin_data)
        
        if element.element_type == 'button':
            applier.apply_to_button(element.widget)
        elif element.element_type == 'slider':
            if prop_name == 'timeline':
                applier.apply_to_timeline_slider(element.widget)
            elif prop_name == 'speed_slider':
                applier.apply_to_speed_slider(element.widget)
        elif element.element_type == 'label':
            applier.apply_to_label(element.widget)
        elif element.element_type == 'control_bar':
            # Background is a bit special, it's a QWidget
            # applier.apply_to_control_bar expects VideoControlsWidget but we passed a QWidget
            # Let's manual apply for now or adapt applier
        # Let's manual apply for now or adapt applier
        # Let's manual apply for now or adapt applier
             styling = self.skin_data.get('video_player', {}).get('styling', {})
             bg_color_str = styling.get('control_bar_color', '#242424')
             bg_color = QColor(bg_color_str)
             
             # Apply opacity
             opacity = styling.get('control_bar_opacity', 0.95)
             bg_color.setAlphaF(opacity)
             
             # Use stylesheet for more reliable background rendering on QWidget
             r, g, b, a = bg_color.red(), bg_color.green(), bg_color.blue(), bg_color.alpha()
             element.widget.setStyleSheet(f"background-color: rgba({r}, {g}, {b}, {a});")
             element.widget.setAutoFillBackground(True)

    def update_element_font(self, element, font):
        """Update element font."""
        # Update styling
        prop_name = element.property_name
        styling = self.skin_data['video_player']['styling']
        
        # We store size, family separately or generic 'font' string?
        # SkinApplier mostly uses 'label_font_size'.
        # Let's add generic font support if possible, or mapping.
        
        if element.element_type == 'label':
            # Labels usually have a font size setting.
            styling['label_font_size'] = font.pointSize()
            # If we want family support, SkinApplier needs update, but we can set stylesheet here.
            styling[f'{prop_name}_font_family'] = font.family()
            styling[f'{prop_name}_font_weight'] = 'bold' if font.bold() else 'normal'
            
        elif element.element_type == 'button':
             # Buttons might just use generic font or specific one?
             # Let's save it.
             styling[f'{prop_name}_font_size'] = font.pointSize()
        
        # Apply directly to widget for immediate feedback
        element.widget.setFont(font)
        # Also need to ensure stylesheet doesn't override it immediately if we use Applier again.
        # But for now, direct set works for visual.

    def update_element_opacity(self, element, opacity):
        """Update element opacity."""
        styling = self.skin_data['video_player']['styling']
        prop_name = element.property_name
        
        if element.element_type == 'control_bar':
            styling['control_bar_opacity'] = opacity
             # Re-apply color with new opacity
            bg_color_str = styling.get('control_bar_color', '#242424')
            bg_color = QColor(bg_color_str)
            bg_color.setAlphaF(opacity)
            
            palette = element.widget.palette()
            palette.setColor(element.widget.backgroundRole(), bg_color)
            element.widget.setPalette(palette)
            # Ensure autoFillBackground is True
            element.widget.setAutoFillBackground(True)
            # Force update
            element.widget.update()
            
        else:
            # For other elements, we might set opacity on the proxy?
            # Or styling['<prop>_opacity'] ?
            styling[f'{prop_name}_opacity'] = opacity
            element.setOpacity(opacity)

    def _save_skin(self):
        """Save current skin to file."""
        if hasattr(self, 'current_skin_path') and self.current_skin_path:
            path = self.current_skin_path
        else:
             skins_dir = Path(__file__).parent.parent / 'skins' / 'user'
             skins_dir.mkdir(parents=True, exist_ok=True)
             path, _ = QFileDialog.getSaveFileName(self, "Save Skin", str(skins_dir), "YAML Files (*.yaml)")
             if not path:
                 return
             self.current_skin_path = Path(path)

        try:
            with open(self.current_skin_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.skin_data, f, default_flow_style=False, sort_keys=False)
            
            QMessageBox.information(self, "Success", f"Skin saved to {self.current_skin_path}")
            
            # Notify manager to reload if attached
            if self.video_controls:
                self.video_controls.skin_manager.refresh_available_skins()
                # We might want to switch to this skin if not already?
                # For now just refreshing is good.

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save skin: {e}")

    def _apply_skin(self):
        """Apply current skin to the running player."""
        if self.video_controls:
            try:
                 if hasattr(self.video_controls, 'apply_skin_data'):
                     self.video_controls.apply_skin_data(self.skin_data)
                     QMessageBox.information(self, "Applied", "Skin applied to player!")
                 else:
                      QMessageBox.warning(self, "Warning", "Video controls does not support direct skin application.")
            except Exception as e:
                QMessageBox.warning(self, "Apply Failed", f"Could not apply skin: {e}")
        else:
            QMessageBox.information(self, "Info", "No active player attached to apply to.")

    def update_element_alignment(self, element, align_type):
        """Update element alignment in skin data."""
        if 'designer_positions' not in self.skin_data:
            self.skin_data['designer_positions'] = {}
        
        prop_pos = self.skin_data['designer_positions'].get(element.property_name, {})
        prop_pos['align'] = align_type
        # Ensure we keep x, y
        if 'x' not in prop_pos: prop_pos['x'] = int(element.x())
        if 'y' not in prop_pos: prop_pos['y'] = int(element.y())
        
        self.skin_data['designer_positions'][element.property_name] = prop_pos
        
        # Update UI
        self._update_alignment_toolbar_state(align_type)

    def clear_element_alignment(self, element):
        """Clear alignment for element (e.g. on manual move)."""
        if 'designer_positions' in self.skin_data:
            positions = self.skin_data['designer_positions']
            if element.property_name in positions:
                if 'align' in positions[element.property_name]:
                    del positions[element.property_name]['align']
                    # Visual update
                    if element == self.selected_item:
                        self._update_alignment_toolbar_state(None)

    def _update_alignment_toolbar_state(self, align_type):
        """Update toolbar buttons checking state."""
        if not hasattr(self, 'align_btns'):
            return
            
        # Uncheck all first
        for btn in self.align_btns.values():
            btn.setChecked(False)
            
        if align_type and align_type in self.align_btns:
            self.align_btns[align_type].setChecked(True)

