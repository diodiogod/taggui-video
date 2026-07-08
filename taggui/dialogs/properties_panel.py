from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout, 
    QSpinBox, QPushButton, QColorDialog, QFontDialog, QSlider
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

class PropertiesPanel(QWidget):
    """Side panel for editing selected element properties."""
    
    def __init__(self, designer):
        super().__init__()
        self.designer = designer
        self.element = None
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Dark Theme Style
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #e0e0e0;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #b0b0b0;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 20px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: #4CAF50;
            }
            QSpinBox {
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-radius: 2px;
                padding: 2px;
            }
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        
        # Title
        self.title_label = QLabel("No Selection")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #fff; margin-bottom: 10px;")
        self.layout.addWidget(self.title_label)
        
        # Grid for POS/SIZE
        pos_group = QGroupBox("Transform")
        pos_layout = QGridLayout()
        
        pos_layout.addWidget(QLabel("X:"), 0, 0)
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-100, 2000)
        self.x_spin.valueChanged.connect(self._on_transform_changed)
        pos_layout.addWidget(self.x_spin, 0, 1)
        
        pos_layout.addWidget(QLabel("Y:"), 0, 2)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-100, 2000)
        self.y_spin.valueChanged.connect(self._on_transform_changed)
        pos_layout.addWidget(self.y_spin, 0, 3)
        
        pos_layout.addWidget(QLabel("W:"), 1, 0)
        self.w_spin = QSpinBox()
        self.w_spin.setRange(10, 2000)
        self.w_spin.valueChanged.connect(self._on_transform_changed)
        pos_layout.addWidget(self.w_spin, 1, 1)
        
        pos_layout.addWidget(QLabel("H:"), 1, 2)
        self.h_spin = QSpinBox()
        self.h_spin.setRange(10, 2000)
        self.h_spin.valueChanged.connect(self._on_transform_changed)
        pos_layout.addWidget(self.h_spin, 1, 3)
        
        pos_group.setLayout(pos_layout)
        self.layout.addWidget(pos_group)
        
        # Style Group
        self.style_group = QGroupBox("Style")
        self.style_layout = QVBoxLayout()
        self.style_group.setLayout(self.style_layout)
        self.layout.addWidget(self.style_group)
        
        # Dynamic style widgets
        self.color_btn = QPushButton("Background Color")
        self.color_btn.clicked.connect(self._pick_color)
        self.style_layout.addWidget(self.color_btn)
        
        self.font_btn = QPushButton("Font ...")
        self.font_btn.clicked.connect(self._pick_font)
        self.style_layout.addWidget(self.font_btn)
        
        # Opacity
        self.style_layout.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.style_layout.addWidget(self.opacity_slider)
        
    def set_element(self, element):
        self.element = element
        self.blockSignals(True)
        
        if not element:
            self.title_label.setText("No Selection")
            self.setEnabled(False)
        else:
            self.setEnabled(True)
            self.title_label.setText(f"Edit: {element.property_name}")
            
            # Update transform
            pos = element.pos()
            rect = element.widget.rect()
            self.x_spin.setValue(int(pos.x()))
            self.y_spin.setValue(int(pos.y()))
            self.w_spin.setValue(int(rect.width()))
            self.h_spin.setValue(int(rect.height()))
            
            # Update style controls based on type
            styling = self.designer.skin_data['video_player']['styling']
            prop_name = element.property_name
            color_val = "#FFFFFF"
            
            if element.element_type == 'button':
                color_val = styling.get(f"{prop_name}_color", styling.get('button_bg_color', '#2b2b2b'))
            elif element.element_type == 'slider':
                if prop_name == 'timeline':
                    color_val = styling.get('timeline_color', '#2196F3')
                elif prop_name == 'speed_slider':
                    color_val = styling.get('speed_gradient_mid', '#6B8E23')
            elif element.element_type == 'label':
                 if prop_name == 'time_label':
                     color_val = styling.get('text_color', '#FFFFFF')
            elif element.element_type == 'control_bar':
                color_val = styling.get('control_bar_color', '#242424')
                
            self.color_btn.setStyleSheet(f"background-color: {color_val}; color: {'#000' if QColor(color_val).lightness() > 128 else '#fff'}")
            
        self.blockSignals(False)
        
    def _on_transform_changed(self):
        if not self.element:
            return
            
        self.element.setPos(self.x_spin.value(), self.y_spin.value())
        self.element.resize(self.w_spin.value(), self.h_spin.value())
        
        # Notify designer to update skin data
        self.designer.update_element_position(self.element, self.x_spin.value(), self.y_spin.value())
        self.designer.update_element_size(self.element, self.w_spin.value(), self.h_spin.value())

    def _pick_color(self):
        if not self.element:
            return
            
        # Determine current color from element styling if possible, or default
        # For now, just default to white or current button color
        current_color = QColor("#FFFFFF")
        
        # We need to know WHICH property to update (bg, text, etc).
        # For this prototype, we'll assume "background" or "main color" based on element type
        
        color = QColorDialog.getColor(current_color, self, "Pick Color")
        if color.isValid():
            # Update the element color visually AND in data
            self.designer.update_element_color(self.element, color)

    def _pick_font(self):
        if not self.element: return
        
        current_font = self.element.widget.font()
        ok, font = QFontDialog.getFont(current_font, self, "Pick Font")
        if ok:
            self.designer.update_element_font(self.element, font)

    def _on_opacity_changed(self, value):
        if not self.element: return
        self.designer.update_element_opacity(self.element, value / 100.0)

