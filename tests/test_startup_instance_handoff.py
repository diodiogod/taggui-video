"""Exercise Windows folder handoff and startup fallback in fresh processes."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
import pytest

from qt_test_helpers import APP, dispose_qobject, pump
from utils.instance_relay import OpenRequestRelay, preferred_server_name, remember_preferred_server_name
from utils.settings import settings


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows early handoff')


def test_running_instance_receives_file_without_loading_gui(tmp_path):
    assert Path(settings.fileName()).resolve() == Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve()
    selected = tmp_path / 'sample.png'
    selected.touch()
    relay = OpenRequestRelay(f'taggui-test-{uuid.uuid4().hex}')
    received = []
    previous = preferred_server_name()
    assert relay.start()
    relay.open_request_received.connect(lambda *request: received.append(request))
    remember_preferred_server_name(relay.server_name)
    process = None
    try:
        script = (
            "import sys; from run_gui import run_gui; "
            "assert run_gui(sys.argv[1:]) == 0; "
            "assert 'widgets.main_window' not in sys.modules"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'taggui'))
        process = subprocess.Popen(
            [sys.executable, '-c', script, '--reuse-instance', str(selected)],
            cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        pump(lambda: process.poll() is not None, seconds=10)
        out, err = process.communicate(timeout=2)
        assert process.returncode == 0, (out, err)
        pump(lambda: bool(received))
        assert received == [(str(tmp_path), str(selected))], (out, err)
        assert b'OpenGL probe' not in out
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        settings.setValue('ipc/last_server_name', previous)
        settings.sync()
        relay.stop()
        dispose_qobject(relay)
        APP.processEvents()


def test_stale_instance_endpoint_falls_back_to_a_new_window(tmp_path):
    assert Path(settings.fileName()).resolve() == Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve()
    previous = preferred_server_name()
    remember_preferred_server_name(f'taggui-missing-{uuid.uuid4().hex}')
    ready = tmp_path / 'startup.ready'
    script = """
import sys
from run_gui import run_gui
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

old_exec = QApplication.exec
def close_after_ready(app):
    QTimer.singleShot(0, app.closeAllWindows)
    return old_exec()
QApplication.exec = close_after_ready
sys.exit(run_gui(sys.argv[1:]))
"""
    try:
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'taggui'),
                   QT_OPENGL='software', TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE='0')
        result = subprocess.run(
            [sys.executable, '-c', script, '--reuse-instance', '--startup-ready-file',
             str(ready), str(tmp_path)],
            cwd=tmp_path, env=env, capture_output=True, timeout=20,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert ready.exists(), (result.stdout, result.stderr)
    finally:
        settings.setValue('ipc/last_server_name', previous)
        settings.sync()
