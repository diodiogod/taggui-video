"""Editable text labels for marking items."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGraphicsTextItem


class MarkingLabel(QGraphicsTextItem):
    """Editable text label attached to marking items."""

    editingFinished = Signal()

    def __init__(self, text, confidence, parent):
        if 0 <= confidence < 1:
            super().__init__(f'{text}: {confidence:.3f}', parent)
        else:
            super().__init__(text, parent)
        self.setDefaultTextColor(Qt.black)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.clearFocus()
            self.editingFinished.emit()
        else:
            super().keyPressEvent(event)
            self.parentItem().setRect(self.sceneBoundingRect())

    def insertFromMimeData(self, source):
        if source.hasText():
            # Insert only the plain text
            cursor = self.textCursor()
            cursor.insertText(source.text())
        else:
            super().insertFromMimeData(source)
        self.parentItem().setRect(self.sceneBoundingRect())

    def changeZoom(self, zoom_factor):
        self.setScale(1/zoom_factor)
        self.parentItem().setRect(self.sceneBoundingRect())
