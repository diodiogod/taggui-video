"""Lazy ONNX inference adapter for the official MI-GAN pipeline."""

from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QRect


_session_lock = threading.RLock()
_cached_session = None
_cached_session_key = None


def _get_session(model_path: Path):
    global _cached_session, _cached_session_key

    path = Path(model_path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    with _session_lock:
        if _cached_session is not None and _cached_session_key == key:
            return _cached_session
        import onnxruntime as ort

        session = ort.InferenceSession(
            str(path),
            providers=['CPUExecutionProvider'],
        )
        _cached_session = session
        _cached_session_key = key
        return session


def inpaint_with_migan(
    image: Image.Image,
    rectangles: list[QRect],
    model_path: Path,
) -> Image.Image:
    """Inpaint rectangles using MI-GAN while preserving pixels outside them."""
    import numpy as np

    rgb_image = image.convert('RGB')
    width, height = rgb_image.size
    hole_mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(hole_mask)
    bounds = QRect(0, 0, width, height)
    for rectangle in rectangles:
        clipped = QRect(rectangle).normalized().intersected(bounds)
        if clipped.isEmpty() or not clipped.isValid():
            continue
        padding = max(2, round(min(width, height) * 0.003))
        left = max(0, clipped.x() - padding)
        top = max(0, clipped.y() - padding)
        right = min(width, clipped.x() + clipped.width() + padding)
        bottom = min(height, clipped.y() + clipped.height() + padding)
        draw.rectangle((left, top, right - 1, bottom - 1), fill=255)

    hole = np.asarray(hole_mask, dtype=np.uint8)
    if not np.any(hole):
        raise ValueError('No valid exclude region was supplied to MI-GAN.')
    image_array = np.asarray(rgb_image, dtype=np.uint8)
    image_input = np.ascontiguousarray(image_array.transpose(2, 0, 1)[None])
    # The official pipeline uses 255 for known pixels and 0 for the hole.
    mask_input = np.ascontiguousarray((255 - hole)[None, None])
    session = _get_session(Path(model_path))
    result = session.run(
        None,
        {'image': image_input, 'mask': mask_input},
    )[0]
    result_array = np.asarray(result[0]).transpose(1, 2, 0).astype(np.uint8)
    # Preserve byte-identical source pixels outside the expanded model mask.
    composed = image_array.copy()
    composed[hole > 0] = result_array[hole > 0]
    output = Image.fromarray(composed, mode='RGB')
    if image.mode == 'RGBA':
        output.putalpha(image.getchannel('A'))
    return output
