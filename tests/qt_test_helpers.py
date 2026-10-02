import time

from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


def pump(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.002)
    assert predicate()
