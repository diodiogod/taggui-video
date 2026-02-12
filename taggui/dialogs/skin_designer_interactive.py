"""Fully Interactive Skin Designer - Pure visual editing, no settings panels."""

from pathlib import Path
from copy import deepcopy
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsItem,
    QColorDialog, QFileDialog, QMessageBox, QLabel,
    QSlider, QFontDialog, QWidget, QGridLayout, QSpinBox,
    QButtonGroup, QMenu
)
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QFont, QIcon, QAction, QPixmap
import yaml

from skins.engine import SkinApplier
from widgets.video_controls import LoopSlider, SpeedSlider, VideoControlsWidget


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

        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self.designer and not self._updating and not self.designer._is_building_mockup:
                return self.designer.get_snapped_position(self, value)

        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if not self._updating and not self.designer._is_building_mockup:
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
        if self.designer:
            self.designer._set_slot_hover(None)
        return QGraphicsItem.mouseReleaseEvent(self, event)

    def contextMenuEvent(self, event):
        """Right-click for options."""
        self.designer.create_context_menu(self, event.screenPos())
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
        self._runtime_sync_pending = False
        self._is_building_mockup = False
        self._slot_rects = []
        self._slot_hover_index = None
        
        # Initialize default skin data
        if video_controls and hasattr(video_controls, 'skin_manager') and video_controls.skin_manager.current_skin:
             self.skin_data = video_controls.skin_manager.current_skin.copy()
        else:
             self.skin_data = self._get_default_skin_data()
        self._initial_skin_data = deepcopy(self.skin_data)
            
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

        # 2.5 Real runtime preview (same widget class as player)
        preview_header = QLabel("Runtime Preview (1:1)")
        preview_header.setStyleSheet("color: #ddd; font-weight: bold; margin-top: 4px;")
        center_layout.addWidget(preview_header)
        self.live_preview_controls = VideoControlsWidget(self)
        self.live_preview_controls.setMinimumHeight(120)
        self.live_preview_controls.setMaximumHeight(220)
        self.live_preview_controls.show()
        center_layout.addWidget(self.live_preview_controls)

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

        reset_layout_btn = QPushButton("↺ Reset Layout")
        reset_layout_btn.setToolTip("Reset alignment/offset/timeline placement and drag positions")
        reset_layout_btn.clicked.connect(self._reset_layout_state)
        btn_layout.addWidget(reset_layout_btn)

        reset_all_btn = QPushButton("⟲ Reset All")
        reset_all_btn.setToolTip("Reset the entire skin in this session to how it was when designer opened")
        reset_all_btn.clicked.connect(self._reset_all_state)
        btn_layout.addWidget(reset_all_btn)

        save_btn = QPushButton("💾 Save Skin")
        save_btn.clicked.connect(self._save_skin)
        
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
        self._refresh_live_preview()

    TOP_ROW_COMPONENTS = {
        'play_button', 'stop_button', 'mute_button',
        'skip_back_button', 'prev_frame_button', 'next_frame_button',
        'skip_forward_button', 'frame_label', 'speed_label',
        'speed_value_label', 'speed_slider',
    }
    TOP_ROW_SWAPPABLE = [
        'play_button',
        'stop_button',
        'mute_button',
        'skip_back_button',
        'prev_frame_button',
        'next_frame_button',
        'skip_forward_button',
    ]

    def _get_runtime_layout_state(self):
        """Read runtime layout directives from skin data."""
        vp = self.skin_data.setdefault('video_player', {})
        layout = vp.setdefault('layout', {})
        designer_layout = vp.setdefault('designer_layout', {})
        controls_row = designer_layout.setdefault('controls_row', {})
        return (
            controls_row.get('button_alignment', layout.get('button_alignment', 'center')),
            int(controls_row.get('offset_x', 0)),
            controls_row.get('timeline_position', layout.get('timeline_position', 'above')),
        )

    def _get_controls_row_config(self):
        vp = self.skin_data.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        return designer_layout.setdefault('controls_row', {})

    def _normalize_button_order(self, order):
        if not isinstance(order, list):
            return list(self.TOP_ROW_SWAPPABLE)
        filtered = [b for b in order if b in self.TOP_ROW_SWAPPABLE]
        for b in self.TOP_ROW_SWAPPABLE:
            if b not in filtered:
                filtered.append(b)
        return filtered

    def _get_button_order(self):
        controls_row = self._get_controls_row_config()
        order = self._normalize_button_order(controls_row.get('button_order'))
        controls_row['button_order'] = order
        return order

    def _get_row_anchor_x(self):
        button_alignment, offset_x, _ = self._get_runtime_layout_state()
        w_control = 900
        btn_size = 40
        spacing = 10
        slot_gap = spacing + 2
        slots_width_total = (len(self.TOP_ROW_SWAPPABLE) * btn_size) + ((len(self.TOP_ROW_SWAPPABLE) - 1) * slot_gap)
        frame_label_w = 50
        frame_spin_w = 80
        speed_label_w = 50
        speed_slider_w = 110
        speed_value_w = 50
        post_slots_gap = 16
        compact_gap = 10
        top_row_total_width = (
            slots_width_total + post_slots_gap +
            frame_label_w + frame_spin_w + compact_gap +
            speed_label_w + speed_slider_w + speed_value_w
        )

        if button_alignment == 'left':
            base_anchor = 20
        elif button_alignment == 'right':
            base_anchor = w_control - top_row_total_width - 20
        else:
            base_anchor = (w_control - top_row_total_width) // 2
        row_anchor_x = int(base_anchor + int(max(-500, min(500, offset_x)) * 0.25))
        return max(20, min(w_control - top_row_total_width - 20, row_anchor_x))

    def _slot_center_for_index(self, row_anchor_x, index):
        slot_width = 52
        return row_anchor_x + (index * slot_width) + 20

    def _nearest_slot_index(self, x, row_anchor_x):
        slot_width = 52
        idx = int(round((x - row_anchor_x - 20) / slot_width))
        return max(0, min(len(self.TOP_ROW_SWAPPABLE) - 1, idx))

    def _swap_button_order(self, component_id, target_index):
        order = self._get_button_order()
        if component_id not in order:
            return
        current_index = order.index(component_id)
        target_index = max(0, min(len(order) - 1, int(target_index)))
        if current_index == target_index:
            return
        order[current_index], order[target_index] = order[target_index], order[current_index]
        self._get_controls_row_config()['button_order'] = order

    def _draw_slot_guides(self, row_anchor_x, y_row1):
        self._slot_rects = []
        dash_pen = QPen(QColor("#6FA8DC"), 2, Qt.PenStyle.DotLine)
        fill_brush = QBrush(QColor(111, 168, 220, 42))
        slot_width = 40
        slot_height = 40
        slot_gap = 12
        for idx in range(len(self.TOP_ROW_SWAPPABLE)):
            x = row_anchor_x + idx * (slot_width + slot_gap)
            rect = self.scene.addRect(x, y_row1, slot_width, slot_height, dash_pen, fill_brush)
            rect.setZValue(-5)
            self._slot_rects.append(rect)

    def _set_slot_hover(self, index):
        """Highlight current drop slot while dragging."""
        if index == self._slot_hover_index:
            return
        self._slot_hover_index = index
        for idx, rect in enumerate(self._slot_rects):
            if idx == index:
                rect.setPen(QPen(QColor("#FFD966"), 3, Qt.PenStyle.SolidLine))
                rect.setBrush(QBrush(QColor(255, 217, 102, 85)))
            else:
                rect.setPen(QPen(QColor("#6FA8DC"), 2, Qt.PenStyle.DotLine))
                rect.setBrush(QBrush(QColor(111, 168, 220, 42)))

    def _draw_area_guides(self, width=900, height=160):
        """Draw clear segmented guide lines for major layout areas."""
        w = int(width)
        h = int(height)

        zone_pen = QPen(QColor("#5C84B8"), 1, Qt.PenStyle.DashLine)
        zone_pen.setCosmetic(True)
        lane_pen = QPen(QColor("#7B889A"), 1, Qt.PenStyle.DotLine)
        lane_pen.setCosmetic(True)

        # Vertical zone separators (left / center / right)
        x1 = int(w * 0.33)
        x2 = int(w * 0.66)
        v1 = self.scene.addLine(x1, 0, x1, h, zone_pen)
        v2 = self.scene.addLine(x2, 0, x2, h, zone_pen)
        v1.setZValue(-8)
        v2.setZValue(-8)

        # Horizontal lanes (top controls / timeline upper / timeline lower / info row)
        for y in (20, 70, 110):
            line = self.scene.addLine(0, y, w, y, lane_pen)
            line.setZValue(-8)

        # Simple labels so areas are explicit
        left_label = self.scene.addText("LEFT AREA")
        center_label = self.scene.addText("CENTER AREA")
        right_label = self.scene.addText("RIGHT AREA")
        left_label.setDefaultTextColor(QColor("#7FA8D8"))
        center_label.setDefaultTextColor(QColor("#7FA8D8"))
        right_label.setDefaultTextColor(QColor("#7FA8D8"))
        left_label.setScale(0.75)
        center_label.setScale(0.75)
        right_label.setScale(0.75)
        left_label.setPos(10, 2)
        center_label.setPos(x1 + 10, 2)
        right_label.setPos(x2 + 10, 2)
        left_label.setZValue(-7)
        center_label.setZValue(-7)
        right_label.setZValue(-7)

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
            if len(items) == 1 and mode in ('left', 'h_center', 'right'):
                alignment_map = {'left': 'left', 'h_center': 'center', 'right': 'right'}
                self._set_controls_row_alignment(alignment_map[mode])
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
        if self._is_building_mockup:
            return
        self._is_building_mockup = True
        try:
            self.scene.clear()
            applier = SkinApplier(self.skin_data)

            layout_data = self.skin_data.get('video_player', {}).get('layout', {})
            h_control = max(160, int(layout_data.get('control_bar_height', 160)))
            w_control = 900

            styling = self.skin_data.get('video_player', {}).get('styling', {})
            bg_color = styling.get('control_bar_color', '#101010')
            bg_opacity = float(styling.get('control_bar_opacity', 0.95))

            bg_widget = QWidget()
            bg_widget.setObjectName("control_bar_bg")
            bg_widget.setStyleSheet(f"background-color: {bg_color}; border-radius: 8px;")
            bg_proxy = InteractiveElement(bg_widget, 0, 0, w_control, h_control, "control_bar", "background", self)
            bg_proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            bg_proxy.setZValue(-10)
            bg_proxy.setOpacity(max(0.0, min(1.0, bg_opacity)))
            self.scene.addItem(bg_proxy)
            self._draw_area_guides(width=w_control, height=h_control)

            positions = self.skin_data.get('designer_positions', {})
            button_alignment, offset_x, timeline_position = self._get_runtime_layout_state()
            button_order = self._get_button_order()

            layout_driven_components = set(self.TOP_ROW_COMPONENTS) | {
                'timeline', 'timeline_slider', 'time_label', 'fps_label',
                'loop_reset_button', 'loop_start_button', 'loop_end_button', 'loop_checkbox',
            }

            def add_widget(widget, name, x, y, w, h, w_type="button", movable=False):
                if w_type == 'button':
                    applier.apply_to_button(widget, component_id=name)
                elif w_type == 'label':
                    applier.apply_to_label(widget, component_id=name)
                pos = {'x': x, 'y': y} if name in layout_driven_components else positions.get(name, {'x': x, 'y': y})
                proxy = InteractiveElement(widget, pos['x'], pos['y'], w, h, w_type, name, self)
                proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
                self.scene.addItem(proxy)
                return proxy

            y_row1 = 20
            btn_size = 40
            spacing = 10
            slot_width = btn_size
            slot_gap = spacing + 2
            slots_width_total = (len(self.TOP_ROW_SWAPPABLE) * slot_width) + ((len(self.TOP_ROW_SWAPPABLE) - 1) * slot_gap)

            frame_label_w = 50
            frame_spin_w = 80
            speed_label_w = 50
            speed_slider_w = 110
            speed_value_w = 50
            post_slots_gap = 16
            compact_gap = 10

            top_row_total_width = (
                slots_width_total + post_slots_gap +
                frame_label_w + frame_spin_w + compact_gap +
                speed_label_w + speed_slider_w + speed_value_w
            )

            if button_alignment == 'left':
                base_anchor = 20
            elif button_alignment == 'right':
                base_anchor = w_control - top_row_total_width - 20
            else:
                base_anchor = (w_control - top_row_total_width) // 2
            row_anchor_x = int(base_anchor + int(max(-500, min(500, offset_x)) * 0.25))
            row_anchor_x = max(20, min(w_control - top_row_total_width - 20, row_anchor_x))

            self._draw_slot_guides(row_anchor_x, y_row1)

            button_specs = {
                'play_button': ('media-playback-start', "▶"),
                'stop_button': ('media-playback-stop', "■"),
                'mute_button': (None, "🔇"),
                'skip_back_button': (None, "<<"),
                'prev_frame_button': ('media-skip-backward', "<"),
                'next_frame_button': ('media-skip-forward', ">"),
                'skip_forward_button': (None, ">>"),
            }

            for idx, component_id in enumerate(button_order):
                icon_name, fallback = button_specs[component_id]
                btn = QPushButton(fallback)
                if icon_name:
                    btn.setIcon(QIcon.fromTheme(icon_name))
                    if not btn.icon().isNull():
                        btn.setText("" if component_id not in ('mute_button',) else fallback)
                slot_x = row_anchor_x + idx * (btn_size + slot_gap)
                add_widget(btn, component_id, slot_x, y_row1, btn_size, btn_size, movable=True)

            x_cursor = row_anchor_x + slots_width_total + post_slots_gap
            frame_lbl = QLabel("Frame:")
            add_widget(frame_lbl, 'frame_label', x_cursor, y_row1 + 10, frame_label_w, 20, 'label', movable=False)
            x_cursor += frame_label_w

            frame_spin = QSpinBox()
            frame_spin.setValue(99)
            frame_spin.setStyleSheet("background: #333; color: white;")
            spin_proxy = InteractiveElement(frame_spin, x_cursor, y_row1, frame_spin_w, 25, "spinbox", "frame_spinbox", self)
            spin_proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self.scene.addItem(spin_proxy)
            x_cursor += frame_spin_w + compact_gap

            speed_lbl = QLabel("Speed:")
            add_widget(speed_lbl, 'speed_label', x_cursor, y_row1 + 10, speed_label_w, 20, 'label', movable=False)
            x_cursor += speed_label_w

            speed = SpeedSlider(Qt.Orientation.Horizontal)
            speed.setMinimum(-200)
            speed.setMaximum(600)
            speed.setValue(100)
            applier.apply_to_speed_slider(speed, component_id='speed_slider')
            speed_proxy = InteractiveElement(speed, x_cursor, y_row1 + 5, speed_slider_w, 30, "slider", "speed_slider", self)
            speed_proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self.scene.addItem(speed_proxy)
            x_cursor += speed_slider_w

            speed_val = QLabel("1.00x")
            add_widget(speed_val, 'speed_value_label', x_cursor, y_row1 + 10, speed_value_w, 20, 'label', movable=False)

            y_row2 = 70 if timeline_position != 'below' else 110
            timeline = LoopSlider(Qt.Orientation.Horizontal)
            timeline.set_loop_markers(20, 80)
            applier.apply_to_timeline_slider(timeline, component_id='timeline_slider')
            timeline.setMinimum(0)
            timeline.setMaximum(100)
            timeline.setValue(50)
            timeline_proxy = InteractiveElement(timeline, 20, y_row2, 860, 30, "slider", "timeline", self)
            timeline_proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.scene.addItem(timeline_proxy)

            y_row3 = 110 if timeline_position != 'below' else 70
            x_cursor = 20
            add_widget(QLabel("00:00.000 / 01:23.456"), 'time_label', x_cursor, y_row3, 180, 20, 'label', movable=False)
            x_cursor += 190
            add_widget(QLabel("60.00 fps"), 'fps_label', x_cursor, y_row3, 80, 20, 'label', movable=False)
            x_cursor += 90
            add_widget(QLabel("0 frames"), 'frame_count_label', x_cursor, y_row3, 90, 20, 'label', movable=False)

            x_loop = 660
            add_widget(QPushButton("✕"), 'loop_reset_button', x_loop, y_row3, 30, 30, movable=False)
            x_loop += 35
            add_widget(QPushButton("◀"), 'loop_start_button', x_loop, y_row3, 30, 30, movable=False)
            x_loop += 35
            add_widget(QPushButton("▶"), 'loop_end_button', x_loop, y_row3, 30, 30, movable=False)
            x_loop += 35
            loop_chk = QPushButton("LOOP")
            loop_chk.setCheckable(True)
            loop_chk.setChecked(True)
            add_widget(loop_chk, 'loop_checkbox', x_loop, y_row3, 55, 30, movable=False)
        finally:
            self._is_building_mockup = False

    def update_element_position(self, element, x, y):
        """Update element position in skin data."""
        if self._is_building_mockup:
            return
        if 'designer_positions' not in self.skin_data:
            self.skin_data['designer_positions'] = {}

        name = element.property_name
        if name in self.TOP_ROW_SWAPPABLE:
            row_anchor_x = self._get_row_anchor_x()
            target_index = self._nearest_slot_index(int(x), row_anchor_x)
            self._swap_button_order(name, target_index)
            QTimer.singleShot(0, self._build_realistic_mockup)
            self._refresh_live_preview()
            return

        self.skin_data['designer_positions'][name] = {'x': int(x), 'y': int(y)}
        self._infer_runtime_layout_from_element_position(element, int(x), int(y))
        if name in self.TOP_ROW_COMPONENTS or name in ('timeline', 'timeline_slider'):
            QTimer.singleShot(0, self._build_realistic_mockup)
        self._refresh_live_preview()

    def _infer_runtime_layout_from_element_position(self, element, x, y):
        """Convert drag gestures into runtime layout intent."""
        # Timeline drag vertical placement maps to timeline position.
        if element.property_name in ('timeline', 'timeline_slider'):
            vp = self.skin_data.setdefault('video_player', {})
            designer_layout = vp.setdefault('designer_layout', {})
            controls_row = designer_layout.setdefault('controls_row', {})
            controls_row['timeline_position'] = 'below' if y >= 95 else 'above'

    def update_element_size(self, element, w, h):
        """Update element size (if applicable)."""
        # For now, we mainly resized via styling for buttons, but if we support arbitrary resizing:
        # We might want to update 'button_size' globally if it's a button, or just this one?
        # For 1:1, usually buttons are uniform.
        # But for 'designer_positions', we could store size overrides too?
        # Let's just pass for now to avoid crash, or implement basic size override storage
        self._refresh_live_preview()
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
            applier.apply_to_button(element.widget, component_id=prop_name)
        elif element.element_type == 'slider':
            if prop_name == 'timeline':
                applier.apply_to_timeline_slider(element.widget, component_id='timeline_slider')
            elif prop_name == 'speed_slider':
                applier.apply_to_speed_slider(element.widget, component_id='speed_slider')
        elif element.element_type == 'label':
            applier.apply_to_label(element.widget, component_id=prop_name)
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

        self._refresh_live_preview()

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
        self._refresh_live_preview()

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
            element.setOpacity(max(0.0, min(1.0, opacity)))
            
        else:
            # For other elements, we might set opacity on the proxy?
            # Or styling['<prop>_opacity'] ?
            styling[f'{prop_name}_opacity'] = opacity
            element.setOpacity(opacity)
        self._refresh_live_preview()

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

    def _refresh_live_preview(self):
        """Apply current in-memory skin to embedded runtime preview."""
        if hasattr(self, 'live_preview_controls') and self.live_preview_controls:
            try:
                self.live_preview_controls.apply_skin_data(self.skin_data)
            except Exception:
                # Keep designer responsive even if preview update fails.
                pass
        # Also sync real player live, throttled to keep UI smooth.
        if self.video_controls and not self._runtime_sync_pending:
            self._runtime_sync_pending = True
            QTimer.singleShot(25, self._sync_runtime_player)

    def _sync_runtime_player(self):
        """Push edits to active player widget without requiring restart."""
        self._runtime_sync_pending = False
        if not self.video_controls:
            return
        try:
            self.video_controls.apply_skin_data(self.skin_data)
        except Exception:
            pass

    def _reset_layout_state(self):
        """Reset layout-related overrides to defaults."""
        vp = self.skin_data.setdefault('video_player', {})
        layout = vp.setdefault('layout', {})
        designer_layout = vp.setdefault('designer_layout', {})
        controls_row = designer_layout.setdefault('controls_row', {})
        controls_row['button_alignment'] = layout.get('button_alignment', 'center')
        controls_row['offset_x'] = 0
        controls_row['timeline_position'] = layout.get('timeline_position', 'above')
        controls_row.pop('button_order', None)
        designer_layout['snap_mode'] = 'zones'
        self.skin_data['designer_positions'] = {}
        QTimer.singleShot(0, self._build_realistic_mockup)
        self._refresh_live_preview()

    def _reset_all_state(self):
        """Reset whole skin state for this session."""
        self.skin_data = deepcopy(self._initial_skin_data)
        QTimer.singleShot(0, self._build_realistic_mockup)
        self._refresh_live_preview()

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

    def _set_controls_row_alignment(self, alignment):
        """Store row-level alignment override for runtime layout."""
        vp = self.skin_data.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        controls_row = designer_layout.setdefault('controls_row', {})
        controls_row['button_alignment'] = alignment
        self._refresh_live_preview()

    def _nudge_controls_row_offset(self, delta):
        """Adjust controls row horizontal offset."""
        vp = self.skin_data.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        controls_row = designer_layout.setdefault('controls_row', {})
        current = int(controls_row.get('offset_x', 0))
        controls_row['offset_x'] = max(-500, min(500, current + int(delta)))
        QTimer.singleShot(0, self._build_realistic_mockup)
        self._refresh_live_preview()

    def get_snap_mode(self):
        """Return snap mode: zones, grid, off."""
        vp = self.skin_data.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        mode = designer_layout.get('snap_mode')
        if mode in ('zones', 'grid', 'off'):
            return mode
        # Backward-compatible fallback.
        if int(designer_layout.get('snap_grid', 10)) > 0:
            return 'grid'
        return 'off'

    def get_snap_grid_size(self):
        """Return active grid size for grid mode."""
        vp = self.skin_data.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        return max(2, int(designer_layout.get('snap_grid', 10)))

    def _default_zone_y(self, component_name):
        if component_name in ('frame_label', 'speed_label', 'speed_value_label'):
            return 30
        if component_name == 'speed_slider':
            return 25
        return 20

    def get_snapped_position(self, element, value):
        """Snap drag target to configured mode."""
        mode = self.get_snap_mode()
        if mode == 'off':
            self._set_slot_hover(None)
            return value

        x = float(value.x())
        y = float(value.y())

        if mode == 'grid':
            grid = self.get_snap_grid_size()
            self._set_slot_hover(None)
            return QPointF(round(x / grid) * grid, round(y / grid) * grid)

        # zones mode (default): snap to meaningful player lanes/areas
        scene_width = int(self.scene.sceneRect().width()) if hasattr(self, 'scene') else 900
        zone_centers = [int(scene_width * 0.18), int(scene_width * 0.50), int(scene_width * 0.82)]

        if element.property_name in self.TOP_ROW_SWAPPABLE:
            row_anchor_x = self._get_row_anchor_x()
            slot_idx = self._nearest_slot_index(x, row_anchor_x)
            self._set_slot_hover(slot_idx)
            snapped_x = row_anchor_x + slot_idx * 52
            return QPointF(snapped_x, 20)

        if element.property_name in self.TOP_ROW_COMPONENTS:
            self._set_slot_hover(None)
            snapped_x = min(zone_centers, key=lambda c: abs(c - x))
            snapped_y = self._default_zone_y(element.property_name)
            return QPointF(snapped_x, snapped_y)

        if element.property_name in ('timeline', 'timeline_slider'):
            self._set_slot_hover(None)
            snapped_y = 70 if abs(y - 70) <= abs(y - 110) else 110
            return QPointF(20, snapped_y)

        self._set_slot_hover(None)
        return value

    def create_context_menu(self, element, screen_pos=None):
        """Context menu for element actions."""
        menu = QMenu(self)

        align_left = menu.addAction("Align Row Left")
        align_center = menu.addAction("Align Row Center")
        align_right = menu.addAction("Align Row Right")
        menu.addSeparator()
        nudge_left = menu.addAction("Nudge Row Left (-20)")
        nudge_right = menu.addAction("Nudge Row Right (+20)")
        reset_offset = menu.addAction("Reset Row Offset")
        reset_layout = menu.addAction("Reset Layout (Default)")
        menu.addSeparator()
        snap_zones = menu.addAction("Snap: Areas (Recommended)")
        snap_grid = menu.addAction("Snap: Grid (10px)")
        snap_off = menu.addAction("Snap: Off")

        choice = menu.exec(screen_pos) if screen_pos is not None else menu.exec()
        if choice == align_left:
            self._set_controls_row_alignment('left')
        elif choice == align_center:
            self._set_controls_row_alignment('center')
        elif choice == align_right:
            self._set_controls_row_alignment('right')
        elif choice == nudge_left:
            self._nudge_controls_row_offset(-20)
        elif choice == nudge_right:
            self._nudge_controls_row_offset(20)
        elif choice == reset_offset:
            vp = self.skin_data.setdefault('video_player', {})
            designer_layout = vp.setdefault('designer_layout', {})
            controls_row = designer_layout.setdefault('controls_row', {})
            controls_row['offset_x'] = 0
            QTimer.singleShot(0, self._build_realistic_mockup)
            self._refresh_live_preview()
        elif choice == reset_layout:
            self._reset_layout_state()
        elif choice == snap_zones:
            vp = self.skin_data.setdefault('video_player', {})
            designer_layout = vp.setdefault('designer_layout', {})
            designer_layout['snap_mode'] = 'zones'
        elif choice == snap_grid:
            vp = self.skin_data.setdefault('video_player', {})
            designer_layout = vp.setdefault('designer_layout', {})
            designer_layout['snap_mode'] = 'grid'
            designer_layout.setdefault('snap_grid', 10)
        elif choice == snap_off:
            vp = self.skin_data.setdefault('video_player', {})
            designer_layout = vp.setdefault('designer_layout', {})
            designer_layout['snap_mode'] = 'off'

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
