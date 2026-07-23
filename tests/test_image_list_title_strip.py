import os
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / 'taggui'
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtWidgets import QApplication

from widgets.image_list_dock import ControlsToggleStrip


def test_activity_strip_hides_title_without_forgetting_it():
    app = QApplication.instance() or QApplication([])
    strip = ControlsToggleStrip(title='Images')

    strip.set_activity_state(True, 'Validating folder changes...')
    assert strip.title_label.text() == ''

    strip.set_title('Secondary Images')
    assert strip.title_label.text() == ''

    strip.set_activity_state(False)
    assert strip.title_label.text() == 'Secondary Images'

    strip.deleteLater()
    app.processEvents()
