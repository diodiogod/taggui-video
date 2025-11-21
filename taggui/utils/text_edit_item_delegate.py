from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QStyledItemDelegate, QStyle

from utils.spell_highlighter import SpellHighlighter
from utils.settings import settings


class TextEditItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_multiplier = 1.0

    def paint(self, painter, option, index):
        # Add some left padding.
        option.rect.adjust(4, 0, 0, 0)
        # Use parent's paint to properly handle text wrapping and alignment
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setFrameStyle(QFrame.Shape.NoFrame)
        editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setStyleSheet('padding-left: 3px;')
        editor.index = index

        # Add spell checking if enabled
        spell_check_enabled = settings.value('spell_check_enabled', defaultValue=True, type=bool)
        spell_highlighter = SpellHighlighter(editor.document())
        spell_highlighter.set_enabled(spell_check_enabled)

        # Load custom dictionary
        custom_dict_list = settings.value('spell_check_custom_dictionary', [], type=list)
        if custom_dict_list:
            custom_dict = set(custom_dict_list)
            spell_highlighter.load_custom_dictionary(custom_dict)

        # Store highlighter reference to prevent garbage collection
        editor._spell_highlighter = spell_highlighter

        return editor

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Base padding + zoom scaled padding
        base_padding = 8
        scaled_padding = int(base_padding * self.zoom_multiplier)
        size.setHeight(size.height() + scaled_padding)
        return size

    def set_zoom_multiplier(self, zoom_percent: int):
        """Set zoom level (as percentage) for row height scaling."""
        self.zoom_multiplier = zoom_percent / 100.0

    def eventFilter(self, editor, event: QEvent):
        if (event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor)
            self.parent().setCurrentIndex(
                self.parent().model().index(editor.index.row(), 0))
            self.parent().selectionModel().select(
                self.parent().model().index(editor.index.row(), 0),
                QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.parent().setFocus()
            return True
        # This is required to prevent crashing when the user clicks on another
        # tag in the All Tags list.
        if event.type() == QEvent.FocusOut:
            self.commitData.emit(editor)
            self.closeEditor.emit(editor)
            return True
        return False
