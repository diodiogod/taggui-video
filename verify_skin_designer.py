import sys
import os

# Ensure we can import taggui package
# Assuming we run this from /home/linux/taggui/taggui
sys.path.append(os.getcwd())

from PySide6.QtWidgets import QApplication
from taggui.dialogs.skin_designer_interactive import SkinDesignerInteractive

def main():
    app = QApplication(sys.argv)
    
    # Create designer
    # We pass None for video_controls, so it should load default skin data
    designer = SkinDesignerInteractive()
    designer.show()
    
    print("Skin Designer launched. Please verify manual interactions:")
    print("1. Drag Play button")
    print("2. Resize Play button")
    print("3. Select Timeline -> Properties Panel matches")
    print("4. Change Color of Play button")
    print("5. Save Skin")
    
    # We exit after a short delay for automated verification that it launches
    # In a real manual run, we'd remove the timer.
    from PySide6.QtCore import QTimer
    QTimer.singleShot(3000, app.quit)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
