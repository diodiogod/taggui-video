"""Paint scene annotations above video widgets without duplicating their state."""
import weakref

from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsItem, QStyle, QStyleOptionGraphicsItem, QWidget


class SceneForegroundOverlay(QWidget):
    """A mouse-transparent presentation of the view's existing foreground items.

    Embedded video widgets cover QGraphicsScene content regardless of item Z.
    The scene still owns input, geometry and persistence; this sibling widget
    only paints its annotation items above those video surfaces.
    """

    def __init__(self, view, accepts_item):
        super().__init__(view.viewport())
        self._view = view
        self._accepts_item = accepts_item
        self._surfaces = weakref.WeakSet()
        self._last_transform = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.hide()
        view.viewport().installEventFilter(self)
        view.scene().changed.connect(self._scene_changed)
        view.horizontalScrollBar().valueChanged.connect(self._scene_changed)
        view.verticalScrollBar().valueChanged.connect(self._scene_changed)

    def sync_surfaces(self, surfaces):
        for surface in surfaces:
            if isinstance(surface, QWidget) and surface not in self._surfaces:
                self._surfaces.add(surface)
                surface.installEventFilter(self)
        visible = False
        for surface in list(self._surfaces):
            try:
                visible |= (surface.parentWidget() is self.parentWidget()
                            and surface.isVisible() and surface.width() > 1 and surface.height() > 1)
            except RuntimeError:
                self._surfaces.discard(surface)
        self.setGeometry(self.parentWidget().rect())
        self.setVisible(visible)
        if visible:
            self.raise_()
            self.update()

    @Slot()
    def _scene_changed(self, *args):
        if self.isVisible():
            self.update()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if watched is self.parentWidget():
            if event_type == QEvent.Type.Resize:
                self.setGeometry(watched.rect())
                self.update()
            elif event_type == QEvent.Type.Paint and self.isVisible():
                # setTransform/centerOn can move the scene without changing
                # any item. Only repaint when mapping changes, avoiding a
                # viewport-paint/overlay-update feedback loop during playback.
                transform = self._view.viewportTransform()
                if transform != self._last_transform:
                    self._last_transform = transform
                    self.update()
        elif event_type in (QEvent.Type.Show, QEvent.Type.Hide,
                            QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.ZOrderChange):
            self._view.image_viewer.raise_viewport_overlays()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(self._view.renderHints())
        viewport_transform = self._view.viewportTransform()
        self._last_transform = viewport_transform
        try:
            for item in self._view.scene().items(Qt.SortOrder.AscendingOrder):
                if not item.isVisible() or not self._accepts_item(item):
                    continue
                transform = item.deviceTransform(viewport_transform)
                if not transform.mapRect(item.boundingRect()).intersects(event.rect()):
                    continue
                option = QStyleOptionGraphicsItem()
                option.initFrom(self._view.viewport())
                option.exposedRect = item.boundingRect()
                option.rect = option.exposedRect.toAlignedRect()
                if item.isSelected():
                    option.state |= QStyle.StateFlag.State_Selected
                if item.hasFocus():
                    option.state |= QStyle.StateFlag.State_HasFocus
                painter.save()
                painter.setWorldTransform(transform)
                painter.setOpacity(item.effectiveOpacity())
                if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemClipsToShape:
                    painter.setClipPath(item.shape())
                item.paint(painter, option, self._view.viewport())
                painter.restore()
        finally:
            painter.end()
