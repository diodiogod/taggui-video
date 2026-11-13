"""Application-owned workers, drained before Qt teardown."""
import threading

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import QApplication


class ArchiveTask(QThread):
    progress = Signal(object)
    completed = Signal(object, str)

    def __init__(self, operation):
        app = QApplication.instance()
        super().__init__(app)
        self.operation = operation
        self.cancel_event = threading.Event()
        # Keep the Python wrapper alive even if its requesting widget disappears.
        if not hasattr(app, '_workflow_archive_tasks'):
            app._workflow_archive_tasks = set()
        app._workflow_archive_tasks.add(self)
        app.aboutToQuit.connect(self.shutdown)
        self.finished.connect(self.release)

    def run(self):
        try:
            result = self.operation(cancel=self.cancel_event, progress=self.progress.emit)
            self.completed.emit(result, '')
        except Exception as error:
            self.completed.emit(None, str(error))

    @Slot()
    def cancel(self):
        self.cancel_event.set()

    @Slot()
    def shutdown(self):
        self.cancel()
        self.wait()

    @Slot()
    def release(self):
        QApplication.instance()._workflow_archive_tasks.discard(self)
        self.deleteLater()
