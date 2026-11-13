"""Small, opt-in maintenance tool for folder-local workflow archives."""
from functools import partial
from pathlib import Path
import time

from PySide6.QtCore import Slot, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout,
)

from utils.settings import DEFAULT_SETTINGS, parse_image_list_formats, settings
from utils.workflow_archive import create_archive, restore_archive
from utils.workflow_archive_task import ArchiveTask

WORKFLOW_ARCHIVE_SHORTCUT = 'Ctrl+Alt+Shift+F7'


class WorkflowArchiveDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('ComfyUI Workflow Archive')
        self.resize(610, 350)
        self.task = None
        layout = QVBoxLayout(self)
        description = QLabel(
            'Save space by packing accompanying ComfyUI JSON workflows into workflows.7z. '
            'Only this folder is processed, not subfolders. TagGUI metadata and unrelated JSON stay untouched. '
            'Ctrl+Alt+drag can retrieve archived workflows. Requires 7-Zip.')
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.folder = QLineEdit(settings.value('directory_path', '', type=str))
        self.browse = QPushButton('Choose Folder…')
        self.browse.clicked.connect(self.choose_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.remove = QCheckBox('Remove original workflow JSON files after verifying the archive')
        self.remove.setChecked(True)
        self.remove.setToolTip(
            'On by default. Removes unchanged workflows already archived, after checking new additions. '
            'Cleanup-only runs reuse the archive without recompressing it. Uncheck to keep loose copies. '
            'Restore puts them back, even after restarting TagGUI. Keep workflows.7z with your media.')
        layout.addWidget(self.remove)
        row = QHBoxLayout()
        self.pack = QPushButton('Create / Update Archive')
        self.restore = QPushButton('Restore Originals')
        self.pack.clicked.connect(self.start_pack)
        self.restore.clicked.connect(self.start_restore)
        self.restore.setToolTip('Undo workflow removal without overwriting existing JSON. The archive is kept.')
        row.addWidget(self.pack)
        row.addWidget(self.restore)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel('Existing archives are preserved and extended. Different versions with the same name are never overwritten.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self._progress_message = ''
        self._started_at = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self.refresh_progress_text)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)

    @Slot()
    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, 'Workflow Folder', self.folder.text())
        if selected:
            self.folder.setText(selected)

    @Slot()
    def start_pack(self):
        suffixes = set(parse_image_list_formats(settings.value(
            'image_list_file_formats', DEFAULT_SETTINGS['image_list_file_formats'], type=str)))
        self.start(partial(create_archive, Path(self.folder.text()), suffixes,
                           remove_originals=self.remove.isChecked()))

    @Slot()
    def start_restore(self):
        self.start(partial(restore_archive, Path(self.folder.text())))

    def start(self, operation):
        if self.task is not None:
            return
        if not self.folder.text().strip() or not Path(self.folder.text()).is_dir():
            self.status.setText('Choose an existing media folder first.')
            return
        self.set_busy(True)
        self.task = ArchiveTask(operation)
        self.task.progress.connect(self.show_progress)
        self.task.completed.connect(self.show_result)
        self.task.finished.connect(self.finish_task)
        self.task.start()

    def set_busy(self, busy):
        for widget in (self.folder, self.browse, self.remove, self.pack, self.restore):
            widget.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setTextVisible(False)
        if busy:
            self._started_at = time.monotonic()
            self._progress_message = 'Starting workflow archive operation…'
            self.refresh_progress_text()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
        self.close_button.setText('Cancel' if busy else 'Close')

    @Slot(object)
    def show_progress(self, update):
        if self.task is not None and self.task.cancel_event.is_set():
            return
        self._progress_message = str(update)
        total = getattr(update, 'total', None)
        if total is None:
            self.progress.setRange(0, 0)
            self.progress.setTextVisible(False)
        else:
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(update.completed if total else 1)
            self.progress.setFormat('%p%')
            self.progress.setTextVisible(True)
        self.refresh_progress_text()

    @Slot()
    def refresh_progress_text(self):
        elapsed = int(time.monotonic() - self._started_at) if self._started_at is not None else 0
        minutes, seconds = divmod(elapsed, 60)
        self.status.setText(f'{self._progress_message}\nElapsed: {minutes}:{seconds:02d}')

    @Slot(object, str)
    def show_result(self, result, error):
        self._elapsed_timer.stop()
        if error:
            self.status.setText(error)
            return
        text = (f'Archived: {result.archived}. Removed originals: {result.removed}. '
                f'Restored: {result.restored}. Already present: {result.unchanged}. '
                f'Unrecognized JSON left alone: {result.skipped}.')
        if result.archived:
            text += f' New workflows: {result.added}. Reused originals: {result.reused}.'
            if not result.archive_updated:
                text += ' Archive reused without recompression.'
            text += f' Workflow size: {result.source_bytes / 1048576:.2f} MiB → {result.archive_bytes / 1048576:.2f} MiB.'
        if result.retained:
            text += f' Kept {len(result.retained)} changed/conflicting files: ' + ', '.join(result.retained[:8])
        self.status.setText(text)

    @Slot()
    def finish_task(self):
        self.task = None
        self.set_busy(False)

    def reject(self):
        if self.task is not None:
            self.task.cancel()
            self._progress_message = 'Cancelling safely… Completed work is kept; Restore can recover removed originals.'
            self.refresh_progress_text()
            return
        super().reject()

    def closeEvent(self, event):
        if self.task is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


def open_workflow_archive_dialog(parent):
    dialog = WorkflowArchiveDialog(parent)
    dialog.exec()
    dialog.deleteLater()
