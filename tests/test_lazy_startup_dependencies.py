import json
import os
from pathlib import Path
from importlib.util import find_spec
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from auto_captioning import models_list
from utils import spell_highlighter


def test_main_window_import_defers_heavy_media_and_spell_modules():
    script = """
import json
import sys
import widgets.main_window
assert not widgets.main_window._is_media_comparison_widget(object())
print(json.dumps({
    name: name in sys.modules
    for name in (
        "cv2",
        "multiprocessing",
        "concurrent.futures.process",
        "exifread",
        "imagesize",
        "spellchecker",
        "widgets.video_player",
        "widgets.video_controls",
        "widgets.media_comparison_widget",
        "widgets.fullscreen_viewer_window",
        "widgets.secondary_browser",
        "skins.engine.skin_manager",
        "PySide6.QtMultimedia",
        "dialogs.settings_dialog",
        "dialogs.export_dialog",
        "dialogs.find_and_replace_dialog",
        "dialogs.batch_reorder_tags_dialog",
        "dialogs.prompt_history_dialog",
        "dialogs.caption_multiple_images_dialog",
    )
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TAGGUI_ROOT)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(result.stdout.strip())
    assert not any(loaded.values()), loaded


def test_video_player_import_defers_opencv_until_fallback():
    script = """
import json
import sys
from widgets import video_player
before = "cv2" in sys.modules
module_name = video_player._get_cv2().__name__
print(json.dumps({
    "before": before,
    "after": "cv2" in sys.modules,
    "module_name": module_name,
    "validator_loaded": "utils.video.validator" in sys.modules,
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TAGGUI_ROOT)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    state = json.loads(result.stdout.strip())
    assert state == {
        "before": False,
        "after": True,
        "module_name": "cv2",
        "validator_loaded": False,
    }


def test_model_registry_import_does_not_load_ml_frameworks():
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
    assert "ultralytics" not in sys.modules
    assert "auto_captioning.auto_captioning_model" not in sys.modules
    assert "auto_captioning.captioning_thread" not in sys.modules
    xcomposer_visible = any("xcomposer2" in model for model in models_list.MODELS)
    assert xcomposer_visible is (find_spec("gptqmodel") is not None)


def test_model_metadata_is_resolved_without_concrete_classes(tmp_path):
    wd_model = tmp_path / "wd-model"
    wd_model.mkdir()
    (wd_model / "model.onnx").touch()
    (wd_model / "selected_tags.csv").touch()

    assert models_list.get_model_kind("Remote") == models_list.MODEL_KIND_REMOTE
    assert (
        models_list.get_model_kind("SmilingWolf/wd-vit-tagger-v3")
        == models_list.MODEL_KIND_WD_TAGGER
    )
    assert (
        models_list.get_model_kind(str(wd_model))
        == models_list.MODEL_KIND_WD_TAGGER
    )
    assert (
        models_list.get_model_artifact_kind("Remote")
        == models_list.MODEL_ARTIFACT_KIND_REMOTE
    )
    assert (
        models_list.get_model_download_revision("vikhyatk/moondream2")
        == "2024-08-26"
    )


def test_model_class_resolution_uses_expected_lazy_adapter(monkeypatch):
    resolutions = []

    def fake_load(module_name, class_name):
        resolutions.append((module_name, class_name))
        return module_name, class_name

    monkeypatch.setattr(models_list, "_load_model_class", fake_load)
    models_list.get_model_class.cache_clear()
    try:
        assert models_list.get_model_class("Remote") == (
            "auto_captioning.models.remote",
            "RemoteGen",
        )
        assert models_list.get_model_class(
            "MiaoshouAI/Florence-2-large-PromptGen-v2.0"
        ) == (
            "auto_captioning.models.florence_2",
            "Florence2Promptgen",
        )
        assert models_list.get_model_class(
            "llava-hf/llava-v1.6-vicuna-13b-hf"
        ) == (
            "auto_captioning.models.llava_next",
            "LlavaNextVicuna",
        )
    finally:
        models_list.get_model_class.cache_clear()

    assert len(resolutions) == 3


def test_spell_dictionary_is_shared_per_language():
    if not spell_highlighter.SPELL_CHECKER_AVAILABLE:
        return
    spell_highlighter._get_spell_checker.cache_clear()
    first = spell_highlighter._get_spell_checker("en")
    second = spell_highlighter._get_spell_checker("en")
    assert first is second


def test_spell_highlighter_defers_dictionary_until_text_is_checked(monkeypatch):
    if not spell_highlighter.SPELL_CHECKER_AVAILABLE:
        return

    calls = []

    class FakeChecker:
        @staticmethod
        def unknown(words):
            return set()

    monkeypatch.setattr(
        spell_highlighter,
        "_get_spell_checker",
        lambda language: calls.append(language) or FakeChecker(),
    )
    highlighter = spell_highlighter.SpellHighlighter()
    assert highlighter.spell_checker is None
    assert calls == []
    assert highlighter.is_misspelled("example") is False
    assert calls == ["en"]


def test_video_utility_exports_do_not_import_editing_suite():
    from utils import video

    assert "utils.video.frame_editor" not in sys.modules
    assert "utils.video.video_editor" not in sys.modules
    assert video.VideoValidator.__name__ == "VideoValidator"
    assert "utils.video.validator" in sys.modules
    assert "cv2" not in sys.modules
    assert "utils.video.ffmpeg_gpu" not in sys.modules
    assert "utils.video.frame_editor" not in sys.modules


def test_playback_backend_import_does_not_probe_optional_runtimes():
    from utils.video import playback_backend

    assert playback_backend.MPV_PYTHON_MODULE is None
    assert playback_backend.VLC_PYTHON_MODULE is None
    assert "mpv" not in sys.modules
    assert "vlc" not in sys.modules
