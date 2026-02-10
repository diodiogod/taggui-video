import logging
import os
import sys
import traceback
import warnings
import io
import threading
import faulthandler
from datetime import datetime

# Suppress ffmpeg verbose output BEFORE any OpenCV imports
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'

try:
    import transformers
    from PySide6.QtGui import QImageReader
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import qInstallMessageHandler

    from utils.settings import settings
    from widgets.main_window import MainWindow
except Exception as e:
    with open('taggui_import_crash.log', 'w') as f:
        f.write(str(e) + "\n" + traceback.format_exc())
    sys.exit(1)


# Install a message handler to suppress QPainter warnings at Qt level
def qt_message_handler(msg_type, msg_context, msg_string):
    """Suppress Qt's QPainter debug messages."""
    if "QPainter" in msg_string or "Paint device returned engine" in msg_string:
        return
    # For development, uncomment to see other messages:
    # print(f"[Qt] {msg_string}")

qInstallMessageHandler(qt_message_handler)

CRASH_LOG_PATH = os.path.abspath('taggui_crash.log')
FATAL_LOG_PATH = os.path.abspath('taggui_fatal.log')
_fatal_log_handle = None
ENABLE_FATAL_CRASH_DUMPS = os.getenv('TAGGUI_ENABLE_FAULTHANDLER', '0') == '1'


def _append_crash_log(title: str, exc_info=None):
    """Append a timestamped crash entry to the crash log."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(CRASH_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"{ts} | {title}\n")
            f.write("=" * 80 + "\n")
            if exc_info is None:
                f.write(traceback.format_exc())
            else:
                f.writelines(traceback.format_exception(*exc_info))
            f.write("\n")
    except Exception as log_error:
        print(f"[CRASH] Failed to write crash log: {log_error}")
    print(f"[CRASH] Details written to: {CRASH_LOG_PATH}")


def install_crash_handlers():
    """Install Python/thread crash handlers; fatal dumps are opt-in."""
    global _fatal_log_handle
    if _fatal_log_handle is not None:
        return

    def _unhandled_exception(exc_type, exc_value, exc_traceback):
        _append_crash_log("UNHANDLED EXCEPTION", (exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _thread_exception(args):
        thread_name = getattr(args.thread, 'name', 'unknown')
        _append_crash_log(
            f"THREAD EXCEPTION ({thread_name})",
            (args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _unhandled_exception
    threading.excepthook = _thread_exception

    # Optional: capture fatal/native crashes (C-extension aborts) with stack dumps.
    if ENABLE_FATAL_CRASH_DUMPS:
        try:
            _fatal_log_handle = open(FATAL_LOG_PATH, 'a', encoding='utf-8', buffering=1)
            _fatal_log_handle.write(
                "\n" + "=" * 80 + "\n"
                f"{datetime.now().isoformat()} | SESSION START pid={os.getpid()}\n"
                + "=" * 80 + "\n"
            )
            faulthandler.enable(file=_fatal_log_handle, all_threads=True)
            print(f"[CRASH] Fatal trace dumps enabled: {FATAL_LOG_PATH}")
        except Exception as e:
            print(f"[WARNING] Could not enable faulthandler: {e}")


def suppress_warnings():
    """Suppress all warnings when not in a development environment."""
    environment = os.getenv('TAGGUI_ENVIRONMENT')
    if environment == 'development':
        print('Running in development environment.')
        return
    logging.getLogger('exifread').setLevel(logging.ERROR)
    logging.basicConfig(level=logging.ERROR)
    warnings.simplefilter('ignore')
    transformers.logging.set_verbosity_error()
    try:
        import auto_gptq
        auto_gptq_logger = logging.getLogger(auto_gptq.modeling._base.__name__)
        auto_gptq_logger.setLevel(logging.ERROR)
    except ImportError:
        pass


def run_gui():
    # Suppress Qt multimedia ffmpeg output
    os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.multimedia*=false'

    app = QApplication([])
    # The application name is shown in the taskbar.
    app.setApplicationName('TagGUI')
    # The application display name is shown in the title bar.
    app.setApplicationDisplayName('TagGUI')
    app.setStyle('Fusion')
    # Disable the allocation limit to allow loading large images.
    QImageReader.setAllocationLimit(0)

    # Warm thumbnail cache singleton on UI thread before worker threads start.
    # This avoids concurrent first-time cache initialization in background loaders.
    try:
        from utils.thumbnail_cache import get_thumbnail_cache
        get_thumbnail_cache()
    except Exception as cache_error:
        print(f"[CACHE INIT] Warmup failed: {cache_error}")

    main_window = MainWindow(app)
    main_window.show()

    # Install signal handler for console close (Windows Ctrl+C, terminal close, etc.)
    def signal_handler(signum, frame):
        print("\n[SHUTDOWN] Console closing, saving settings...")
        # Save settings directly (closeEvent might not fire during forced shutdown)
        geom = main_window.saveGeometry()
        state = main_window.saveState()
        print(f"[SHUTDOWN] Saving geometry: {len(geom)} bytes")
        print(f"[SHUTDOWN] Saving state: {len(state)} bytes")
        settings.setValue('geometry', geom)
        settings.setValue('window_state', state)
        if hasattr(main_window, 'toolbar_manager'):
            settings.setValue('fixed_marker_size', main_window.toolbar_manager.fixed_marker_size_spinbox.value())
        if hasattr(main_window, 'image_list_model'):
            main_window.image_list_model._flush_db_cache_flags()
        settings.sync()  # Force write to disk
        print("[SHUTDOWN] Settings saved and synced")
        # Now close and exit
        main_window.close()
        sys.exit(0)

    import signal
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    # Windows-specific: handle console window close
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        # Console control handler function type
        HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        @HANDLER_ROUTINE
        def windows_console_handler(event):
            if event in (0, 2, 5, 6):  # CTRL_C, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN
                print("\n[SHUTDOWN] Console closing, saving settings...")
                # Save settings directly (closeEvent might not fire during forced shutdown)
                geom = main_window.saveGeometry()
                state = main_window.saveState()
                print(f"[SHUTDOWN] Saving geometry: {len(geom)} bytes")
                print(f"[SHUTDOWN] Saving state: {len(state)} bytes")
                settings.setValue('geometry', geom)
                settings.setValue('window_state', state)
                if hasattr(main_window, 'toolbar_manager'):
                    settings.setValue('fixed_marker_size', main_window.toolbar_manager.fixed_marker_size_spinbox.value())
                if hasattr(main_window, 'image_list_model'):
                    main_window.image_list_model._flush_db_cache_flags()
                settings.sync()  # Force write to disk
                print("[SHUTDOWN] Settings saved and synced")
                main_window.close()
                return True
            return False

        try:
            kernel32.SetConsoleCtrlHandler(windows_console_handler, True)
        except Exception as e:
            print(f"[WARNING] Could not install Windows console handler: {e}")

    return int(app.exec())


if __name__ == '__main__':
    # Suppress all warnings when not in a development environment.
    suppress_warnings()
    install_crash_handlers()
    try:
        sys.exit(run_gui())
    except Exception as exception:
        _append_crash_log("TOP-LEVEL EXCEPTION", sys.exc_info())
        # DON'T clear settings on every crash - only show error
        # settings.clear()  # REMOVED: This destroys user's recent files/settings on any crash
        error_message_box = QMessageBox()
        error_message_box.setWindowTitle('Error')
        error_message_box.setIcon(QMessageBox.Icon.Critical)
        error_message_box.setText(str(exception))
        error_message_box.setDetailedText(traceback.format_exc())
        error_message_box.exec()
        print(f"[CRASH] Fatal trace dump path: {FATAL_LOG_PATH}")
        sys.exit(1)
