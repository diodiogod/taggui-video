#!/usr/bin/env python3
"""
TagGUI launcher script.

Run this from the project root to start TagGUI.
"""

import sys
from pathlib import Path

# Add the taggui package directory to Python path
project_root = Path(__file__).parent
taggui_package = project_root / "taggui"
sys.path.insert(0, str(taggui_package))

# Now import and run - imports will work relative to taggui package
if __name__ == '__main__':
    from run_gui import run_gui, suppress_warnings
    suppress_warnings()
    run_gui()
