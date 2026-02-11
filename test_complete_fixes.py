#!/usr/bin/env python3
"""Test transparency fix and position offsets."""

import sys
from pathlib import Path

project_root = Path("/mnt/j/Aitools/MyTagGUI/taggui_working")
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "taggui"))

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer
from taggui.widgets.video_controls import VideoControlsWidget
from taggui.skins.engine import SkinManager


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Complete Fixes Test")
        self.setGeometry(100, 100, 1000, 500)

        central = QWidget()
        self.setCentralWidget(central)

        # Gradient background to test transparency
        central.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #FF1744, stop:0.33 #FFC107,
                    stop:0.66 #00E676, stop:1 #2979FF);
            }
        """)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(50, 50, 50, 50)

        label = QLabel(
            "Test Results:\n"
            "1. Control bar background should be semi-transparent (see gradient through it)\n"
            "2. Buttons should be fully opaque\n"
            "3. Play button should be at x=150 (moved from default)\n"
            "4. Stop button should be at x=250 (moved from default)"
        )
        label.setStyleSheet("background: white; padding: 10px; border-radius: 4px;")
        layout.addWidget(label)

        layout.addStretch()

        # Create controls
        self.controls = VideoControlsWidget()
        layout.addWidget(self.controls)

        # Load skin with custom settings
        skin_manager = SkinManager()
        skin_manager.load_default_skin()
        self.controls.skin_manager = skin_manager

        if skin_manager.current_skin:
            # Set bright yellow background with 70% opacity (should be visible)
            skin_manager.current_skin['video_player']['styling']['control_bar_color'] = '#FFFF00'
            skin_manager.current_skin['video_player']['styling']['control_bar_opacity'] = 0.7

            # Add test position offsets
            if 'designer_positions' not in skin_manager.current_skin:
                skin_manager.current_skin['designer_positions'] = {}

            skin_manager.current_skin['designer_positions']['play_button'] = {'x': 150, 'y': 10}
            skin_manager.current_skin['designer_positions']['stop_button'] = {'x': 250, 'y': 10}

        self.controls.apply_current_skin()

        print("Expected:")
        print("  - Yellow background at 70% opacity (gradient visible through it)")
        print("  - Play button at x=150")
        print("  - Stop button at x=250")

        QTimer.singleShot(200, self.check_results)

    def check_results(self):
        print("\nActual results:")

        # Check background
        palette = self.controls.palette()
        bg_color = palette.color(self.controls.backgroundRole())
        print(f"  Background color: {bg_color.name()} with alpha: {bg_color.alpha()}/255")

        # Check positions
        print(f"  Play button position: {self.controls.play_pause_btn.pos()}")
        print(f"  Stop button position: {self.controls.stop_btn.pos()}")

        # Verify
        if bg_color.alpha() > 0 and bg_color.alpha() < 255:
            print("\n✓ Transparency works!")
        else:
            print("\n✗ Transparency broken - alpha should be between 0 and 255")

        if self.controls.play_pause_btn.pos().x() == 150:
            print("✓ Position offsets work!")
        else:
            print(f"✗ Position offsets broken - play button should be at x=150")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
