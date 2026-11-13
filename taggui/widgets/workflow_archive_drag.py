"""Prepare archived files without blocking the native drag input handler."""
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QPersistentModelIndex, QModelIndex, Qt, Slot
from PySide6.QtWidgets import QApplication, QToolTip

from utils.workflow_archive import drag_cache
from utils.workflow_archive_task import ArchiveTask


class WorkflowArchiveDrag(QObject):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.task = None
        self.request = None

    def prepare(self, indices, origin, actions):
        if self.task is not None:
            return False
        pending = []
        identities = []
        for index in indices:
            media = index.data(Qt.ItemDataRole.UserRole)
            path = getattr(media, 'path', None)
            if path is None:
                continue
            path = Path(path)
            identities.append((QPersistentModelIndex(index), path))
            if (not drag_cache.lookup(path)[0]
                    and self.view._workflow_sidecar_drag_path_for_image_path(path) is None):
                pending.append(path)
        if not pending:
            return True
        self.request = (QPersistentModelIndex(origin), actions, identities)
        self.task = ArchiveTask(partial(drag_cache.prepare, pending))
        self.task.completed.connect(self.prepared)
        self.task.finished.connect(self.finished)
        self.notify('Preparing archived workflows… Keep holding Ctrl+Alt and the mouse, or drag again when ready.')
        self.task.start()
        return False

    def notify(self, message):
        # Tooltips do not change the browser's content geometry.
        QToolTip.showText(self.view.mapToGlobal(self.view.rect().center()), message, self.view, self.view.rect(), 6000)

    @Slot(object, str)
    def prepared(self, result, error):
        self.error = error

    @Slot()
    def finished(self):
        self.task = None
        origin, actions, identities = self.request
        self.request = None
        if getattr(self, 'error', ''):
            self.notify('Could not prepare workflow: ' + self.error)
            return
        required = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        held = (QApplication.mouseButtons() & Qt.MouseButton.LeftButton
                and QApplication.keyboardModifiers() & required == required)
        # Never revive a drag after the mouse was released or after a model
        # refresh/selection change redirected its media identity.
        current = {QPersistentModelIndex(i) for i in self.view.selectedIndexes()}
        expected = {i for i, _ in identities}
        valid = origin.isValid() and all(
            i.isValid() and getattr(i.data(Qt.ItemDataRole.UserRole), 'path', None) == path
            for i, path in identities)
        if held and valid and (current == expected or len(expected) == 1 and origin not in current):
            self.view._start_spawn_drag_for_index(QModelIndex(origin), actions)
        else:
            self.notify('Archived workflows are ready. Ctrl+Alt+drag again to export them.')
