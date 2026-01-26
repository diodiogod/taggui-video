import logging
import os
import sys
import traceback
import warnings
import io

# Suppress ffmpeg verbose output BEFORE any OpenCV imports
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'

import transformers
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import qInstallMessageHandler

from utils.settings import settings
from widgets.main_window import MainWindow


# Install a message handler to suppress QPainter warnings at Qt level
def qt_message_handler(msg_type, msg_context, msg_string):
    """Suppress Qt's QPainter debug messages."""
    if "QPainter" in msg_string or "Paint device returned engine" in msg_string:
        return
    # For development, uncomment to see other messages:
    # print(f"[Qt] {msg_string}")

qInstallMessageHandler(qt_message_handler)


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

    sys.exit(app.exec())


if __name__ == '__main__':
    # Suppress all warnings when not in a development environment.
    suppress_warnings()
    try:
        run_gui()
    except Exception as exception:
        # DON'T clear settings on every crash - only show error
        # settings.clear()  # REMOVED: This destroys user's recent files/settings on any crash
        error_message_box = QMessageBox()
        error_message_box.setWindowTitle('Error')
        error_message_box.setIcon(QMessageBox.Icon.Critical)
        error_message_box.setText(str(exception))
        error_message_box.setDetailedText(traceback.format_exc())
        error_message_box.exec()
        raise exception
