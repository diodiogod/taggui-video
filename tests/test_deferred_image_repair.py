from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from widgets import image_viewer as module


def test_deferred_repair_preserves_new_selection_and_browser(monkeypatch, tmp_path):
    callbacks, repairs, saves = [], [], []
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda delay, callback: callbacks.append(callback))
    monkeypatch.setattr(module, 'repair_mismatched_image_extension_path',
                        lambda path, **kwargs: repairs.append(path) or path.with_suffix('.png'))
    source = SimpleNamespace(_directory_path=tmp_path, _db=None)
    proxy = SimpleNamespace(sourceModel=lambda: source)
    image = SimpleNamespace(path=tmp_path / 'image.jpg')
    viewer = SimpleNamespace(
        current_media=image, proxy_image_list_model=proxy,
        _normalize_proxy_index=lambda index: module.QModelIndex(),
        _invalidate_current_thumbnail_after_path_repair=lambda *args, **kwargs: None,
        _persist_repaired_selection_path=saves.append,
    )
    schedule = module.ImageViewer._schedule_deferred_extension_repair
    schedule(viewer, image)
    viewer.current_media = SimpleNamespace(path=tmp_path / 'new.jpg')
    callbacks.pop()()
    assert not repairs and not saves
    viewer.current_media = image
    schedule(viewer, image)
    source._directory_path = tmp_path / 'other'
    callbacks.pop()()
    assert not repairs and not saves
    source._directory_path = tmp_path
    schedule(viewer, image)
    callbacks.pop()()
    assert repairs == [tmp_path / 'image.jpg']
    assert saves == [tmp_path / 'image.png']
