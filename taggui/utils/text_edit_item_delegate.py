from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QStyledItemDelegate


class TextEditItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Add some left padding.
        option.rect.adjust(4, 0, 0, 0)
        # Skip super().paint() to avoid Qt's internal pixmap allocation issues
        # Manually paint the item instead
        if not painter or not painter.isActive():
            return
        if not index.isValid():
            return

        # Paint background if selected
        if option.state & option.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        # Paint the icon/decoration
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and not icon.isNull():
            icon_rect = option.rect.adjusted(2, 2, -option.rect.width() + 34, -2)
            icon.paint(painter, icon_rect.x(), icon_rect.y(), icon_rect.width(), icon_rect.height())

        # Paint the text
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            text_rect = option.rect.adjusted(36, 2, -2, -2)
            painter.setPen(option.palette.text().color())
            painter.drawText(text_rect, Qt.AlignVCenter, str(text))

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setFrameStyle(QFrame.Shape.NoFrame)
        editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setStyleSheet('padding-left: 3px;')
        editor.index = index
        return editor

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 8)
        return size

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
