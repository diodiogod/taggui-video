import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent


APP = QApplication.instance() or QApplication([])


def dispose_widget(widget):
    """Destroy standalone test widgets while their model owners are alive.

    close() only hides an ordinary QWidget. Leaving its cycles for Python GC
    can destroy native graphics objects during a later test's Qt delivery.
    Callers must first drain workers which hold file/model resources.
    """
    widget.close()
    dispose_qobject(widget)


def dispose_qobject(owner):
    """Complete native deletion; callers first drain workers and dependants."""
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)


def pump(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.002)
    assert predicate()


def assert_capture_contains_color(image, color, *, tolerance=25, minimum_fraction=.1):
    """Validate known fixture pixels; a white/blank successful capture must fail too."""
    assert not image.isNull(), 'Capture returned no pixels'
    sample = image.scaled(32, 32)
    matched = sum(all(abs(channel - expected) <= tolerance for channel, expected in
                      zip(sample.pixelColor(x, y).getRgb()[:3], color))
                  for y in range(sample.height()) for x in range(sample.width()))
    assert matched >= sample.width() * sample.height() * minimum_fraction, 'Expected fixture color is absent from capture'
