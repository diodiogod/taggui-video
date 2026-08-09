import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image
from PySide6.QtCore import QRect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from utils import migan_inpainter


class _FakeSession:
    def __init__(self):
        self.inputs = None

    def run(self, _outputs, inputs):
        self.inputs = inputs
        image = inputs['image']
        result = np.zeros_like(image)
        result[:, 0, :, :] = 255
        return [result]


def test_migan_adapter_uses_official_nchw_contract_and_preserves_outside_mask(
        tmp_path, monkeypatch):
    session = _FakeSession()
    model_path = tmp_path / 'migan.onnx'
    model_path.write_bytes(b'model')
    monkeypatch.setattr(migan_inpainter, '_get_session', lambda _path: session)
    source = Image.new('RGB', (20, 20), (10, 20, 30))

    result = migan_inpainter.inpaint_with_migan(
        source,
        [QRect(8, 8, 4, 4)],
        model_path,
    )

    assert session.inputs['image'].shape == (1, 3, 20, 20)
    assert session.inputs['image'].dtype == np.uint8
    assert session.inputs['mask'].shape == (1, 1, 20, 20)
    assert session.inputs['mask'][0, 0, 9, 9] == 0
    assert session.inputs['mask'][0, 0, 0, 0] == 255
    assert result.getpixel((9, 9)) == (255, 0, 0)
    assert result.getpixel((0, 0)) == (10, 20, 30)


def test_importing_migan_adapter_does_not_import_onnxruntime():
    code = (
        "import sys; import utils.migan_inpainter; "
        "print('onnxruntime' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, '-c', code],
        cwd=ROOT / 'taggui',
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == 'False'
