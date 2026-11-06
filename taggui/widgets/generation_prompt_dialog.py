"""On-demand, non-persistent generation-prompt viewer."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QToolButton, QToolTip, QVBoxLayout,
)

from utils.generation_prompt import read_generation_prompts
from utils.latest_task import LatestTask
from widgets.generation_prompt_navigation import PromptNavigator


_copy_request = 0


def _new_copy_request():
    global _copy_request
    _copy_request += 1
    return _copy_request


def open_generation_prompt(parent, media, *, copy_on_load=False, list_view=None, viewer=None, index=None):
    """Open a prompt for the explicit media owner captured at invocation."""
    if media is None or not getattr(media, 'path', None):
        QMessageBox.information(parent, 'Generation Prompt', 'Select an image or video first.')
        return None
    dialog = GenerationPromptDialog(Path(media.path), parent, copy_on_load=copy_on_load,
                                    list_view=list_view, viewer=viewer, index=index)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    if copy_on_load:
        QToolTip.showText(QCursor.pos(), 'Reading generation prompt…', parent)
    else:
        dialog.show()
    return dialog


class GenerationPromptDialog(QDialog):
    def __init__(self, path, parent=None, *, copy_on_load=False, list_view=None, viewer=None, index=None):
        super().__init__(parent)
        self.path = Path(path)
        self._copy_on_load = bool(copy_on_load)
        self._copy_request = _new_copy_request() if copy_on_load else None
        self._candidates = []
        self.setWindowTitle('Generation Prompt')
        self.resize(700, 420)

        layout = QVBoxLayout(self)
        self.filename = QLabel(self.path.name, self)
        self.filename.setToolTip(str(self.path))
        self.filename.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.filename)
        self.source = QComboBox(self)
        self.source.currentIndexChanged.connect(self._select_candidate)
        self.source.setVisible(False)
        layout.addWidget(self.source)
        self.info = QLabel('Reading media metadata…', self)
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                          | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        self.previous_button = QToolButton(self)
        self.previous_button.setArrowType(Qt.ArrowType.LeftArrow)
        self.previous_button.setToolTip('Previous image or video')
        self.previous_button.setAccessibleName('Previous image or video')
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        buttons.addWidget(self.previous_button)
        self.next_button = QToolButton(self)
        self.next_button.setArrowType(Qt.ArrowType.RightArrow)
        self.next_button.setToolTip('Next image or video')
        self.next_button.setAccessibleName('Next image or video')
        self.next_button.clicked.connect(lambda: self._navigate(1))
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        self.copy_button = QPushButton('Copy Prompt', self)
        self.copy_button.setEnabled(False)
        self.copy_button.setMinimumWidth(110)
        self.copy_button.clicked.connect(self._copy_prompt)
        buttons.addWidget(self.copy_button)
        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.timeout.connect(self._update_copy_button_label)
        self.text.selectionChanged.connect(self._update_copy_button_label)
        close_button = QPushButton('Close', self)
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._worker = LatestTask(self, name='generation-prompt')
        self._worker.completed.connect(self._loaded)
        self._navigator = None
        if list_view is not None or viewer is not None:
            self._navigator = PromptNavigator(self.path, list_view=list_view, viewer=viewer,
                                              index=index, parent=self)
            self._navigator.changed.connect(self._update_navigation)
            self._navigator.navigated.connect(self._show_media_prompt)
            self._navigator.failed.connect(self.info.setText)
        self._update_navigation()
        self._worker.submit(read_generation_prompts, self.path)

    def _update_navigation(self):
        previous, next_ = self._navigator.availability() if self._navigator is not None else (False, False)
        self.previous_button.setEnabled(previous)
        self.next_button.setEnabled(next_)

    def _navigate(self, direction):
        if self._navigator is None:
            return
        # A dialog opened after an ambiguous copy request must not copy a new
        # file automatically when the user browses to it.
        self._copy_on_load = False
        self._navigator.move(direction)

    def _show_media_prompt(self, path):
        self.path = Path(path)
        self.filename.setText(self.path.name)
        self.filename.setToolTip(str(self.path))
        self._candidates = []
        self.source.blockSignals(True)
        self.source.clear()
        self.source.blockSignals(False)
        self.source.setVisible(False)
        self.text.clear()
        self.info.setText('Reading media metadata…')
        self.copy_button.setEnabled(False)
        self._copy_feedback_timer.stop()
        self._update_copy_button_label()
        self._worker.submit(read_generation_prompts, self.path)

    @Slot(int, object, object)
    def _loaded(self, _token, candidates, error):
        if self._copy_on_load and self._copy_request != _copy_request:
            self.close()
            return
        if self._copy_on_load:
            QToolTip.hideText()
        if error is not None:
            self.info.setText(f'Could not read media metadata: {error}')
            self.show()
            return
        self._candidates = candidates or []
        if not self._candidates:
            self.info.setText('No positive prompt was found in this file or its workflow sidecar.')
            self.show()
            return
        self.source.blockSignals(True)
        for candidate in self._candidates:
            self.source.addItem(candidate.label)
        self.source.blockSignals(False)
        self.source.setVisible(len(self._candidates) > 1)
        self._select_candidate(0)
        if (self._copy_on_load and len(self._candidates) == 1
                and self._candidates[0].verified):
            self._copy_prompt(automatic=True)
            QToolTip.showText(QCursor.pos(), 'Positive prompt copied', self.parentWidget())
            self.close()
        elif self._copy_on_load:
            self.show()

    @Slot(int)
    def _select_candidate(self, index):
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        prefix = ('Multiple positive prompt sources found. Choose one to copy. '
                  if len(self._candidates) > 1 else '')
        self.info.setText(prefix + (candidate.note or candidate.label))
        self.text.setPlainText(candidate.text)
        self.copy_button.setEnabled(True)
        self._update_copy_button_label()

    def _update_copy_button_label(self):
        self.copy_button.setText('Copy Selected' if self.text.textCursor().hasSelection()
                                 else 'Copy Prompt')

    def _copy_prompt(self, *, automatic=False):
        cursor = self.text.textCursor()
        if not automatic and cursor.hasSelection():
            # Qt uses paragraph separators in selectedText(), even for plain text.
            text = cursor.selectedText().replace('\u2029', '\n')
        else:
            text = self.text.toPlainText()
        if not text:
            return
        if not automatic:
            _new_copy_request()
        QApplication.clipboard().setText(text)
        self.copy_button.setText('Copied!')
        self._copy_feedback_timer.start(1800)

    def closeEvent(self, event):
        if self._navigator is not None:
            self._navigator.close()
        self._worker.close()
        super().closeEvent(event)
