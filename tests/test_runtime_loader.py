from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from utils.video.runtime_loader import RuntimeLoader
from utils.video import playback_backend


@pytest.mark.parametrize('fail', [False, True])
def test_pending_requests_share_completion_and_cache_failures(fail):
    entered, release = Event(), Event()
    calls = []
    module = object()

    def importer(name):
        calls.append(name)
        entered.set()
        assert release.wait(5)
        if fail:
            raise OSError('missing runtime')
        return module

    loader = RuntimeLoader(importer)
    assert loader.snapshot('mpv').status == 'unrequested'
    assert loader.request('mpv').status == 'pending'
    assert entered.wait(2)
    try:
        for _ in range(20):
            assert loader.request('mpv').status == 'pending'
        with ThreadPoolExecutor(2) as pool:
            waiting = pool.submit(loader.load, 'mpv')
            release.set()
            state = waiting.result(timeout=2)
        assert calls == ['mpv']
        assert state.status == ('failed' if fail else 'ready')
        assert state.module is (None if fail else module)
        assert state.error == ('OSError: missing runtime' if fail else '')
        assert loader.request('mpv') == state
        assert loader.load('mpv') == state
        assert calls == ['mpv']
    finally:
        release.set()
        loader.load('mpv')


def test_backend_pending_does_not_publish_false_failure(monkeypatch):
    release = Event()
    module = object()
    def importer(name):
        assert release.wait(5)
        return module
    loader = RuntimeLoader(importer)
    monkeypatch.setattr(playback_backend, '_RUNTIME_LOADER', loader)
    monkeypatch.setattr(playback_backend, 'MPV_PYTHON_MODULE', None)
    monkeypatch.setattr(playback_backend, 'MPV_BACKEND_AVAILABLE', False)
    monkeypatch.setattr(playback_backend, 'MPV_BACKEND_ERROR', '')
    try:
        assert playback_backend.request_playback_backend('mpv_experimental').status == 'pending'
        assert playback_backend.MPV_BACKEND_ERROR == ''
        release.set()
        assert playback_backend.load_playback_backend('mpv_experimental') is module
        assert playback_backend.MPV_BACKEND_AVAILABLE
        assert playback_backend.request_playback_backend('mpv_experimental').module is module
    finally:
        release.set()
        loader.load('mpv')
