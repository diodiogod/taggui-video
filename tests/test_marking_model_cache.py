from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from auto_marking import model_cache


def test_class_metadata_persists_and_invalidates_with_model_file(
        tmp_path, monkeypatch):
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model-v1")
    cache_path = tmp_path / "classes.json"
    monkeypatch.setattr(model_cache, "_METADATA_CACHE_PATH", cache_path)
    model_cache._RUNTIME_CACHE.clear()

    signature = model_cache._model_signature(model_path)
    model_cache._write_class_metadata(signature, {0: "person", 1: "hand"})

    assert model_cache.get_cached_model_classes(model_path) == {
        0: "person",
        1: "hand",
    }

    model_path.write_bytes(b"model-v2-with-a-different-size")

    assert model_cache.get_cached_model_classes(model_path) is None


def test_runtime_cache_loads_unchanged_model_once(tmp_path, monkeypatch):
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model")
    loads = []

    class FakeYOLO:
        def __init__(self, path, task=None):
            loads.append((Path(path), task))
            self.names = {0: "person", 1: "hand"}

    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=FakeYOLO),
    )
    monkeypatch.setattr(
        model_cache,
        "configure_ultralytics_marking_runtime",
        lambda path: None,
    )
    monkeypatch.setattr(
        model_cache,
        "infer_marking_model_task",
        lambda path: "detect",
    )
    monkeypatch.setattr(
        model_cache,
        "_preferred_device",
        lambda path: "cuda",
    )
    monkeypatch.setattr(
        model_cache,
        "_METADATA_CACHE_PATH",
        tmp_path / "classes.json",
    )
    model_cache._RUNTIME_CACHE.clear()

    first = model_cache.load_marking_runtime(model_path)
    second = model_cache.load_marking_runtime(model_path)

    assert first is second
    assert first.model_names == {0: "person", 1: "hand"}
    assert len(loads) == 1
