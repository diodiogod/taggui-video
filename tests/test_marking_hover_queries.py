from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRect, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QColor, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QWidget

from qt_test_helpers import APP, dispose_widget
from utils.image import ImageMarking
from utils.rect import RectPosition
from widgets.marking import MarkingItem
from widgets.marking_view import ImageGraphicsView


def test_hover_reuses_exact_scene_hits_without_stale_cross_event_cache(monkeypatch):
    scene = QGraphicsScene()
    viewer = SimpleNamespace(_is_video_loaded=False)
    view = ImageGraphicsView(scene, viewer)
    view.setViewport(QWidget())
    view.resize(400, 300)
    view.setSceneRect(0, 0, 400, 300)
    large = MarkingItem(QRect(30, 30, 160, 160), ImageMarking.HINT, False)
    small = MarkingItem(QRect(50, 50, 50, 50), ImageMarking.HINT, False)
    scene.addItem(large)
    scene.addItem(small)
    pixels = QImage(400, 300, QImage.Format_ARGB32)
    pixels.fill(QColor(0, 0, 0, 0))
    background = QGraphicsPixmapItem(QPixmap.fromImage(pixels))
    background.setZValue(-1)
    scene.addItem(background)
    original = scene.items
    queries = []
    chosen = []
    preferred = view._preferred_marking_region_at

    def hits(*args):
        if args and isinstance(args[0], QPointF):
            queries.append(args[0])
        return original(*args)

    def record(pos, **kwargs):
        result = preferred(pos, **kwargs)
        chosen.append(result)
        return result

    monkeypatch.setattr(scene, 'items', hits)
    monkeypatch.setattr(view, '_preferred_marking_region_at', record)
    monkeypatch.setattr(MarkingItem, 'handle_selected', RectPosition.NONE)
    try:
        for hidden, expected in ((False, small), (True, large)):
            small.setVisible(not hidden)
            position = QPointF(view.mapFromScene(QPointF(75, 75)))
            event = QMouseEvent(QEvent.MouseMove, position, position,
                               Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            queries.clear()
            view.mouseMoveEvent(event)
            assert len(queries) == 1
            assert chosen[-1] is expected
        assert view._marking_regions_at(QPointF(75, 75), scene_items=[]) == []
        queries.clear()
        monkeypatch.setattr(MarkingItem, 'handle_selected', RectPosition.CENTER)
        view.mouseMoveEvent(event)
        assert queries == []
        monkeypatch.setattr(MarkingItem, 'handle_selected', RectPosition.NONE)
        view.insertion_mode = True
        monkeypatch.setattr(view, 'update_lines_pos', lambda: None)
        view.mouseMoveEvent(event)
        assert queries == []
    finally:
        scene.clear()
        dispose_widget(view)
        APP.processEvents()
