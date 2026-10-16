"""Run blocking file work behind a responsive, cancellable Qt dialog."""
import threading


class BackgroundOperationCancelled(Exception):
    pass


def check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BackgroundOperationCancelled()


def run_background_operation(operation, *, title, label, should_cancel=None):
    """operation(update, cancelled) must use only worker-owned data/resources.

    The modal event loop preserves synchronous callers while Qt keeps painting
    and accepting Cancel. Cancellation never joins a potentially blocked file
    read. The daemon owns no Qt objects and can finish after its dialog dies.
    """
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialog, QProgressDialog

    cancelled = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    state = {'progress': (label, None, None), 'result': None, 'error': None}

    def update(text, count=None, maximum=None):
        check_cancelled(cancelled)
        with lock:
            state['progress'] = (text, count, maximum)

    def run():
        try:
            result = operation(update, cancelled)
            check_cancelled(cancelled)
            state['result'] = result
        except Exception as error:
            state['error'] = error
        finally:
            finished.set()

    dialog = QProgressDialog(label, 'Cancel', 0, 0, QApplication.activeWindow())
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.canceled.connect(cancelled.set)
    timer = QTimer(dialog)
    timer.setInterval(50)

    def poll():
        if should_cancel is not None and should_cancel():
            dialog.reject()
            return
        if finished.is_set():
            dialog.done(QDialog.Accepted)
            return
        with lock:
            text, count, maximum = state['progress']
        dialog.setRange(0, 0 if maximum is None else max(1, maximum))
        if count is not None and maximum is not None:
            dialog.setValue(count)
        dialog.setLabelText(text if count is None else f'{text}\nFiles: {count:,}')

    timer.timeout.connect(poll)
    worker = threading.Thread(target=run, name='directory-load', daemon=True)
    try:
        # Start only once the native dialog is participating in Qt delivery.
        QTimer.singleShot(0, dialog, worker.start)
        timer.start()
        accepted = dialog.exec() == QDialog.Accepted
    finally:
        timer.stop()
        cancelled.set()
        dialog.deleteLater()
    if not accepted:
        raise BackgroundOperationCancelled()
    if state['error'] is not None:
        raise state['error']
    return state['result']
