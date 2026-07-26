import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"


def test_run_gui_dispatches_model_download_worker_before_ui_imports(tmp_path):
    payload_path = tmp_path / "payload.json"
    result_path = tmp_path / "result.txt"
    error_path = tmp_path / "error.txt"
    payload_path.write_text('{"mode": "unsupported"}', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TAGGUI_ROOT / "run_gui.py"),
            "--taggui-model-download-worker",
            str(payload_path),
            str(result_path),
            str(error_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert not result_path.exists()
    assert "Unsupported download mode" in error_path.read_text(
        encoding="utf-8"
    )


def test_camie_tagger_adapter_contract_in_isolated_process():
    script = r"""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

import numpy as np
from PIL import Image

from auto_captioning.models import camie_tagger as camie_module
from auto_captioning import auto_captioning_model as base_model_module


def logit(probability):
    return np.log(probability / (1.0 - probability))


initial_probabilities = np.array(
    [[0.01, 0.02, 0.03, 0.04, 0.99, 0.98, 0.97]],
    dtype=np.float32,
)
refined_probabilities = np.array(
    [[0.99, 0.90, 0.60, 0.95, 0.80, 0.75, 0.70]],
    dtype=np.float32,
)
initial_logits = logit(initial_probabilities).astype(np.float32)
refined_logits = logit(refined_probabilities).astype(np.float32)
selected_candidates = np.array([[0, 1, 2, 3, 4, 5, 6]], dtype=np.int64)


class FakeInferenceSession:
    def __init__(self, model_path, *args, **kwargs):
        assert Path(model_path).name == "camie-tagger-v2.onnx"
        assert kwargs["providers"] == ["CPUExecutionProvider"]
        self._inputs = [
            SimpleNamespace(name="images", shape=[None, 3, 512, 512])
        ]
        self._outputs = [
            SimpleNamespace(
                name="initial_predictions",
                shape=[None, refined_logits.shape[1]],
            ),
            SimpleNamespace(
                name="refined_predictions",
                shape=[None, refined_logits.shape[1]],
            ),
            SimpleNamespace(
                name="selected_candidates",
                shape=[None, selected_candidates.shape[1]],
            ),
        ]

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, output_names, inputs):
        image_batch = inputs["images"]
        assert image_batch.shape == (1, 3, 512, 512)
        outputs = {
            "initial_predictions": initial_logits,
            "refined_predictions": refined_logits,
            "selected_candidates": selected_candidates,
        }
        if output_names is None:
            return [outputs[output.name] for output in self._outputs]
        return [outputs[name] for name in output_names]


metadata = {
    "model_info": {"img_size": 512},
    "dataset_info": {
        "total_tags": refined_logits.shape[1],
        "tag_mapping": {
            "tag_to_idx": {
                "rating_general": 0,
                "blue_hair": 1,
                "red_dress": 2,
                "green_eyes": 3,
                "1girl": 4,
                "yellow_bow": 5,
                "solo": 6,
            },
            "idx_to_tag": {
                "0": "rating_general",
                "1": "blue_hair",
                "2": "red_dress",
                "3": "green_eyes",
                "4": "1girl",
                "5": "yellow_bow",
                "6": "solo",
            },
            "tag_to_category": {
                "rating_general": "rating",
                "blue_hair": "general",
                "red_dress": "general",
                "green_eyes": "general",
                "1girl": "general",
                "yellow_bow": "general",
                "solo": "general",
            },
        },
    },
}

camie_module.ort.InferenceSession = FakeInferenceSession
camie_module.ort.get_available_providers = lambda: ["CPUExecutionProvider"]

with tempfile.TemporaryDirectory() as temporary_directory:
    model_directory = Path(temporary_directory)
    (model_directory / "camie-tagger-v2.onnx").touch()
    (model_directory / "camie-tagger-v2-metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    tagger = camie_module.CamieTagger.__new__(camie_module.CamieTagger)
    tagger.model_id = str(model_directory)
    tagger.device = SimpleNamespace(type="cpu")
    tagger.caption_settings = {"gpu_index": 0}
    model = tagger.get_model()

    model_inputs = np.zeros((1, 3, 512, 512), dtype=np.float32)
    tags, probabilities = model.generate_tags(
        model_inputs,
        {
            "min_probability": 0.65,
            "max_tags": 2,
            "tags_to_exclude": "green eyes",
        },
    )

    assert tags == ("blue hair", "1girl")
    np.testing.assert_allclose(
        probabilities,
        (0.90, 0.80),
        rtol=1e-5,
        atol=1e-6,
    )

    tagger.model = model

    wide_image = Image.new("RGB", (4, 2), (255, 0, 0))
    tagger.load_image = lambda image, crop: wide_image
    wide_inputs = tagger.get_model_inputs("", object(), False)

    assert wide_inputs.shape == (1, 3, 512, 512)
    assert wide_inputs.dtype == np.float32

    expected_padding = (
        np.array([124, 116, 104], dtype=np.float32) / 255.0
        - np.array([0.485, 0.456, 0.406], dtype=np.float32)
    ) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    expected_red = (
        np.array([1.0, 0.0, 0.0], dtype=np.float32)
        - np.array([0.485, 0.456, 0.406], dtype=np.float32)
    ) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    np.testing.assert_allclose(
        wide_inputs[0, :, 0, 0],
        expected_padding,
        rtol=1e-5,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        wide_inputs[0, :, 256, 256],
        expected_red,
        rtol=1e-5,
        atol=1e-6,
    )

    tall_image = Image.new("RGB", (2, 4), (255, 0, 0))
    tagger.load_image = lambda image, crop: tall_image
    tall_inputs = tagger.get_model_inputs("", object(), False)

    assert tall_inputs.shape == (1, 3, 512, 512)
    assert tall_inputs.dtype == np.float32
    np.testing.assert_allclose(
        tall_inputs[0, :, 0, 0],
        expected_padding,
        rtol=1e-5,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        tall_inputs[0, :, 256, 256],
        expected_red,
        rtol=1e-5,
        atol=1e-6,
    )

    class MissingRefinedOutputSession(FakeInferenceSession):
        def get_outputs(self):
            return [
                SimpleNamespace(
                    name="initial_predictions",
                    shape=[None, refined_logits.shape[1]],
                ),
                SimpleNamespace(
                    name="other_predictions",
                    shape=[None, refined_logits.shape[1]],
                ),
            ]

    camie_module.ort.InferenceSession = MissingRefinedOutputSession
    try:
        tagger.get_model()
    except RuntimeError as exc:
        assert "refined_predictions" in str(exc)
    else:
        raise AssertionError(
            "Camie adapter accepted a named model without refined predictions"
        )
    finally:
        camie_module.ort.InferenceSession = FakeInferenceSession

captured_downloads = []
download_tagger = camie_module.CamieTagger.__new__(camie_module.CamieTagger)
download_tagger.thread = SimpleNamespace(
    models_directory_path=None,
    current_stage=None,
    is_canceled=False,
)
download_tagger._run_cancelable_hf_download = (
    lambda payload, **kwargs: captured_downloads.append((payload, kwargs))
)
download_revision = download_tagger.get_download_revision(
    "Camais03/camie-tagger-v2"
)
assert download_revision == camie_module.CAMIE_TAGGER_REVISION
download_tagger._download_model_assets(
    "Camais03/camie-tagger-v2",
    revision=download_revision,
    resumable=False,
)

assert len(captured_downloads) == 1
download_payload, download_kwargs = captured_downloads[0]
assert download_payload["mode"] == "files"
assert set(download_payload["filenames"]) == {
    "camie-tagger-v2.onnx",
    "camie-tagger-v2-metadata.json",
}
assert len(download_payload["filenames"]) == 2
assert download_payload["revision"] == camie_module.CAMIE_TAGGER_REVISION
assert download_kwargs["model_id"] == "Camais03/camie-tagger-v2"

captured_hf_downloads = []
camie_module.huggingface_hub.hf_hub_download = (
    lambda **kwargs: captured_hf_downloads.append(kwargs)
    or str(Path(tempfile.gettempdir()) / kwargs["filename"])
)
camie_module._resolve_model_asset(
    "Camais03/camie-tagger-v2",
    "camie-tagger-v2.onnx",
)
assert captured_hf_downloads == [{
    "repo_id": "Camais03/camie-tagger-v2",
    "filename": "camie-tagger-v2.onnx",
    "revision": camie_module.CAMIE_TAGGER_REVISION,
}]

worker_paths = [
    Path(tempfile.gettempdir()) / filename
    for filename in ("payload.json", "result.txt", "error.txt")
]
source_command = base_model_module._build_hf_download_command(*worker_paths)
assert source_command[:2] == [sys.executable, "-u"]
assert Path(source_command[2]).name == "model_download_worker.py"
assert source_command[3:] == [str(path) for path in worker_paths]

sys.frozen = True
try:
    frozen_command = base_model_module._build_hf_download_command(*worker_paths)
finally:
    del sys.frozen
assert frozen_command == [
    sys.executable,
    base_model_module.MODEL_DOWNLOAD_WORKER_FLAG,
    *(str(path) for path in worker_paths),
]

from PySide6.QtWidgets import QApplication
from widgets.auto_captioner import AutoCaptioner, CaptionSettingsForm


app = QApplication.instance() or QApplication([])


def select_model_for_ui_test(form, model_id):
    signals_were_blocked = form.model_combo_box.blockSignals(True)
    try:
        form.model_combo_box.setCurrentText(model_id)
    finally:
        form.model_combo_box.blockSignals(signals_were_blocked)
    form.show_settings_for_model(model_id)


classic_form = CaptionSettingsForm(use_compact_style=False)
classic_form.build_page("classic")
select_model_for_ui_test(classic_form, "Camais03/camie-tagger-v2")
assert not classic_form.device_combo_box.isHidden()
assert not classic_form.gpu_index_spin_box.isHidden()
assert classic_form.load_in_4_bit_container.isHidden()
select_model_for_ui_test(classic_form, "SmilingWolf/wd-vit-tagger-v3")
assert classic_form.device_combo_box.isHidden()
assert classic_form.gpu_index_spin_box.isHidden()

compact_form = CaptionSettingsForm(use_compact_style=True)
compact_form.build_page("compact")
select_model_for_ui_test(compact_form, "Camais03/camie-tagger-v2")
assert not compact_form.compact_device_gpu_row.isHidden()
assert compact_form.load_in_4_bit_container.isHidden()
select_model_for_ui_test(compact_form, "SmilingWolf/wd-vit-tagger-v3")
assert compact_form.compact_device_gpu_row.isHidden()


class FinishedThread:
    def __init__(self):
        self.model = SimpleNamespace(processor=object(), model=object())
        self.delete_requested = False

    def deleteLater(self):
        self.delete_requested = True


finished_thread = FinishedThread()
finished_model_wrapper = finished_thread.model
auto_captioner = SimpleNamespace(captioning_thread=finished_thread)
AutoCaptioner._release_finished_captioning_thread(
    auto_captioner,
    finished_thread,
)

assert auto_captioner.captioning_thread is None
assert finished_thread.model is None
assert finished_model_wrapper.processor is None
assert finished_model_wrapper.model is None
assert finished_thread.delete_requested is True

new_thread = FinishedThread()
auto_captioner.captioning_thread = new_thread
AutoCaptioner._release_finished_captioning_thread(
    auto_captioner,
    finished_thread,
)
assert auto_captioner.captioning_thread is new_thread
assert new_thread.model is not None
assert new_thread.delete_requested is False
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
    )

    assert result.returncode == 0, result.stdout + result.stderr
