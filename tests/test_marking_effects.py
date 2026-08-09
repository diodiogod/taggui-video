import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import QRect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from utils.marking_effects import apply_exclude_effect


def test_black_effect_changes_only_exclude_rectangle(tmp_path):
    image_path = tmp_path / 'image.png'
    Image.new('RGB', (20, 20), (255, 255, 255)).save(image_path)

    success, _message = apply_exclude_effect(
        image_path,
        [QRect(5, 6, 4, 3)],
        'black',
    )

    assert success
    with Image.open(image_path) as result:
        assert result.getpixel((5, 6)) == (0, 0, 0)
        assert result.getpixel((8, 8)) == (0, 0, 0)
        assert result.getpixel((4, 6)) == (255, 255, 255)
        assert result.getpixel((9, 8)) == (255, 255, 255)


def test_effect_rejects_empty_rectangle_list(tmp_path):
    image_path = tmp_path / 'image.png'
    Image.new('RGB', (10, 10), (255, 255, 255)).save(image_path)

    success, message = apply_exclude_effect(image_path, [], 'blur')

    assert not success
    assert 'No exclude markings' in message


def test_fast_inpaint_reconstructs_excluded_patch(tmp_path):
    image_path = tmp_path / 'image.png'
    image = Image.new('RGB', (30, 30), (240, 240, 240))
    for x in range(10, 20):
        for y in range(10, 20):
            image.putpixel((x, y), (0, 0, 0))
    image.save(image_path)

    success, _message = apply_exclude_effect(
        image_path,
        [QRect(10, 10, 10, 10)],
        'inpaint (fast)',
    )

    assert success
    with Image.open(image_path) as result:
        assert result.getpixel((15, 15))[0] > 100


def test_ai_inpaint_dispatches_to_migan(tmp_path, monkeypatch):
    image_path = tmp_path / 'image.png'
    model_path = tmp_path / 'migan.onnx'
    model_path.write_bytes(b'model')
    Image.new('RGB', (20, 20), (255, 255, 255)).save(image_path)

    def fake_inpaint(image, rectangles, received_model_path):
        assert len(rectangles) == 1
        assert received_model_path == model_path
        return Image.new('RGB', image.size, (12, 34, 56))

    monkeypatch.setattr(
        'utils.migan_inpainter.inpaint_with_migan',
        fake_inpaint,
    )
    success, _message = apply_exclude_effect(
        image_path,
        [QRect(5, 5, 5, 5)],
        'inpaint — AI (MI-GAN)',
        model_path=model_path,
    )

    assert success
    with Image.open(image_path) as result:
        assert result.getpixel((5, 5)) == (12, 34, 56)
