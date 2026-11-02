"""Focused wall preferences, shared with the main Settings dialog."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
                               QKeySequenceEdit, QLabel, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from utils.settings import DEFAULT_SETTINGS, settings
from utils.settings_widgets import SettingsBigCheckBox, SettingsComboBox


class WallLayoutSettings(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        layout = QVBoxLayout(self)
        intro = QLabel('Saved preferences. Changes apply immediately.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for title, rows in (
            ('Automatic arrangement', (
                ('floating_wall_reflow_after_resize', 'Arrange automatically after resizing',
                 'Apply the layout when you release a resize. Alt skips one gesture.'),
                ('floating_wall_automatic_sizing', 'Allow other windows to resize',
                 'Fit unlocked windows into available space, preserving their proportions. '
                 'When off, arrangement changes positions only.'),
                ('floating_wall_preserve_manual_sizes', 'Remember sizes I change',
                 'A manual resize keeps that window’s size for later arrangements. '
                 'Choose Flexible on the window to release it.'),
            )),
            ('Dragging and previews', (
                ('floating_wall_anchor_drag', 'Ctrl-drag to pin a window',
                 'Preview the other windows around it. Release to pin; Escape cancels. '
                 'This explicit gesture also works when automatic arrangement is off.'),
                ('floating_wall_anchor_snapping', 'Snap to screen edges and other pins',
                 'Respect the wall gap. Hold Shift during Ctrl-drag to suppress snapping.'),
                ('floating_wall_resize_preview', 'Show ghosts while resizing',
                 'Amber marks the resized window’s destination; blue marks the others. '
                 'Available when automatic arrangement is on.'),
            )),
            ('Appearance', (
                ('floating_wall_constraint_icons', 'Show lock icons',
                 'Small translucent marks in the bottom-left corner. Click a mark to release its lock.'),
            )),
        ):
            group = QGroupBox(title)
            content = QVBoxLayout(group)
            for key, label, description in rows:
                self.add_option(content, key, label, description)
            if title == 'Automatic arrangement':
                row = QHBoxLayout()
                row.addWidget(QLabel('Toggle shortcut'))
                self.shortcut = QKeySequenceEdit()
                self.shortcut.setObjectName('floating_wall_manual_shortcut')  # Retain saved bindings.
                self.shortcut.setMaximumSequenceLength(1)
                self.shortcut.setToolTip('Toggle automatic resize arrangement. Clear to disable.')
                self.shortcut.editingFinished.connect(self.save_shortcut)
                row.addWidget(self.shortcut)
                content.addLayout(row)
            layout.addWidget(group)

        self.advanced_button = QToolButton()
        self.advanced_button.setText('Advanced')
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_button.setCheckable(True)
        self.advanced_button.setArrowType(Qt.RightArrow)
        self.advanced_button.setObjectName('wall_advanced_toggle')
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        self.add_option(advanced_layout, 'floating_viewer_rearrange_preserve_screen_order',
                        'Keep the current visual order',
                        'May leave more empty space. Position pins take precedence over this preference.')
        advanced_layout.addWidget(QLabel('Default packing algorithm'))
        algorithm = SettingsComboBox(key='floating_wall_algorithm')
        algorithm.setObjectName('floating_wall_algorithm')
        algorithm.addItems(['Best fit', 'Masonry', 'MaxRects'])
        self.controls['floating_wall_algorithm'] = algorithm
        advanced_layout.addWidget(algorithm)
        hint = QLabel('Best fit compares candidates. The wall menu keeps all algorithm choices '
                      'available for session testing. Walls with pins use obstacle-aware packing.')
        hint.setWordWrap(True)
        advanced_layout.addWidget(hint)
        self.advanced.hide()
        self.advanced_button.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_button)
        layout.addWidget(self.advanced)
        settings.change.connect(self.sync_controls)
        self.sync_controls()

    def add_option(self, layout, key, label, description):
        control = SettingsBigCheckBox(key=key, text=label)
        control.setObjectName(key)
        control.setToolTip(description)
        self.controls[key] = control
        layout.addWidget(control)
        hint = QLabel(description)
        hint.setWordWrap(True)
        hint.setContentsMargins(24, 0, 0, 5)
        font = hint.font()
        font.setPointSizeF(max(8, font.pointSizeF() * .85))
        hint.setFont(font)
        layout.addWidget(hint)

    def toggle_advanced(self, expanded):
        self.advanced_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.advanced.setVisible(expanded)

    def save_shortcut(self):
        settings.setValue('floating_wall_manual_shortcut', self.shortcut.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText))

    def sync_controls(self, *_):
        for key, control in self.controls.items():
            blocked = control.blockSignals(True)
            default = DEFAULT_SETTINGS[key]
            value = settings.value(key, default, type=type(default))
            if isinstance(default, bool):
                control.setChecked(value)
            else:
                control.setCurrentText(value)
            control.blockSignals(blocked)
        self.shortcut.setKeySequence(QKeySequence(settings.value(
            'floating_wall_manual_shortcut', DEFAULT_SETTINGS['floating_wall_manual_shortcut'], type=str)))
        self.controls['floating_wall_resize_preview'].setEnabled(
            self.controls['floating_wall_reflow_after_resize'].isChecked())
        self.controls['floating_wall_anchor_snapping'].setEnabled(
            self.controls['floating_wall_anchor_drag'].isChecked())


class WallLayoutSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Wall settings')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(580, 690)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(WallLayoutSettings())
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
