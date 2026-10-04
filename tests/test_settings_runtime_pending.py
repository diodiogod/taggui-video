from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QComboBox
from PySide6.QtTest import QTest
from qt_test_helpers import dispose_widget
from dialogs import settings_dialog
from utils.video.runtime_loader import RuntimeState


class RuntimeDialog(QDialog):
    _on_playback_backend_changed = settings_dialog.SettingsDialog._on_playback_backend_changed
    _refresh_video_backend_availability = settings_dialog.SettingsDialog._refresh_video_backend_availability

    def __init__(self):
        super().__init__()
        self.warning_label = QLabel(self)
        self.mpv_download_btn = QPushButton(self)
        self.video_playback_backend_combo = QComboBox(self)
        self.video_playback_backend_combo.addItem('MPV', 'mpv_experimental')
        self.video_playback_backend_combo.addItem('Qt', 'qt_hybrid')


def test_settings_pending_is_not_reported_as_failed_and_latest_choice_wins(monkeypatch):
    state = [RuntimeState('pending')]
    monkeypatch.setattr(settings_dialog, 'request_playback_backend', lambda name: state[0])
    monkeypatch.setattr(settings_dialog, 'resolve_runtime_playback_backend', lambda name: name)
    dialog = RuntimeDialog()
    try:
        dialog._on_playback_backend_changed('mpv_experimental')
        assert 'Preparing' in dialog.warning_label.text()
        assert dialog.mpv_download_btn.isHidden()
        dialog.video_playback_backend_combo.setCurrentIndex(1)
        state[0] = RuntimeState('ready')
        dialog._on_playback_backend_changed('qt_hybrid')
        current = dialog.warning_label.text()
        QTest.qWait(80)
        assert dialog.warning_label.text() == current
        assert 'Qt Hybrid' in current
    finally:
        dispose_widget(dialog)


def test_settings_pending_callback_is_cancelled_on_native_deletion(monkeypatch):
    calls = []
    monkeypatch.setattr(settings_dialog, 'request_playback_backend',
                        lambda name: calls.append(name) or RuntimeState('pending'))
    dialog = RuntimeDialog()
    dialog._on_playback_backend_changed('mpv_experimental')
    dispose_widget(dialog)
    QTest.qWait(80)
    assert calls == ['mpv_experimental']
