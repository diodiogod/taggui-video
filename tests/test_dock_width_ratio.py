from pathlib import Path
import sys

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from controllers.dock_width_ratio import DockWidthRatioController
from qt_test_helpers import APP, dispose_widget


def settle():
    QTest.qWait(500)


def test_window_roundtrip_keeps_ratio_despite_minimum_width_and_new_drag():
    # Qt only: no application services, settings, or cache roots are opened.
    window = QMainWindow()
    center = QWidget()
    center.setMinimumWidth(400)
    window.setCentralWidget(center)
    dock = QDockWidget('Images', window)
    dock.setWidget(QWidget())
    window.addDockWidget(Qt.LeftDockWidgetArea, dock)
    controller = DockWidthRatioController(window, dock)
    try:
        window.resize(1200, 600)
        window.show()
        settle()
        window.resizeDocks([dock], [700], Qt.Horizontal)
        settle()
        original = dock.width()
        assert abs(controller._ratio - original / window.width()) < .002

        for _ in range(2):
            window.resize(650, 600)
            settle()
            assert dock.width() < original * 650 / 1200 - 50
            assert controller.preserve_ratio
            window.resize(1200, 600)
            settle()
            assert abs(dock.width() - original) <= 2

        # Exercise Qt's actual separator input after the automatic resize.
        separator = QPoint(dock.geometry().right() + 3, 250)
        QTest.mousePress(window, Qt.LeftButton, pos=separator)
        APP.processEvents()
        target = separator - QPoint(180, 0)
        APP.sendEvent(window, QMouseEvent(
            QEvent.MouseMove, QPointF(target), QPointF(window.mapToGlobal(target)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        ))
        QTest.qWait(100)
        QTest.mouseRelease(window, Qt.LeftButton, pos=separator - QPoint(180, 0))
        settle()
        dragged_width = dock.width()
        assert dragged_width < original - 100
        assert not controller.preserve_ratio
        window.resize(900, 600)
        settle()
        assert abs(dock.width() - dragged_width * .75) <= 2
        window.resize(1200, 600)
        settle()
        assert abs(dock.width() - dragged_width) <= 2

        window.showMaximized()
        settle()
        maximized_width = dock.width()
        assert abs(maximized_width - dragged_width * window.width() / 1200) <= 2
        window.showNormal()
        settle()
        assert abs(dock.width() - dragged_width) <= 2
        window.showMaximized()
        settle()
        assert abs(dock.width() - maximized_width) <= 2
    finally:
        dispose_widget(window)
