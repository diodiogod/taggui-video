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
    if len(sys.argv) >= 2 and sys.argv[1] == '--import-marking-model':
        from utils.marking_model_importer import main as import_marking_model_main
        raise SystemExit(import_marking_model_main(sys.argv[2:]))
    from multiprocessing import freeze_support
    from run_gui import run_gui, suppress_warnings, install_crash_handlers
    freeze_support()
    suppress_warnings()
    install_crash_handlers()
    sys.exit(run_gui(sys.argv[1:]))
