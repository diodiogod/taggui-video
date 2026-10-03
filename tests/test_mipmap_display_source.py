"""Display-source scaling must match Qt's original full-source scaling."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColorSpace, QImage, QPixmap

from qt_test_helpers import APP
from widgets.image_viewer import ImageViewer


@pytest.mark.parametrize('format', [QImage.Format_ARGB32, QImage.Format_RGBA8888,
                                   QImage.Format_RGB32, QImage.Format_RGBA64])
@pytest.mark.parametrize('divisor', [2, 4, 8, 16, 32])
@pytest.mark.parametrize('opaque', [False, True])
def test_display_source_scaling_preserves_pixels(format, divisor, opaque):
    # Reproducible varied colors, alpha edges, odd sizes and fine detail.
    raw = np.random.default_rng(42).integers(0, 256, (399, 513, 4), dtype=np.uint8)
    raw[:, :, 3] = 255 if opaque else np.arange(513, dtype=np.uint16) % 256
    image = QImage(raw.data, 513, 399, raw.strides[0], QImage.Format_RGBA8888).copy()
    image = image.convertToFormat(format)
    image.setColorSpace(QColorSpace.SRgb)
    original = image.copy()
    full = QPixmap.fromImage(image)
    owner = SimpleNamespace(_static_source_qimage=image, _static_mipmap_pixmaps={1: full})
    actual = ImageViewer._get_static_mipmap_pixmap(owner, divisor)
    expected = QPixmap.fromImage(image.scaled(round(513/divisor), round(399/divisor),
                                              Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    assert actual.toImage().convertToFormat(QImage.Format_ARGB32) == expected.toImage().convertToFormat(QImage.Format_ARGB32)
    assert actual.toImage().colorSpace() == expected.toImage().colorSpace()
    assert owner._static_source_qimage is image
    assert image == original
    assert ImageViewer._get_static_mipmap_pixmap(owner, divisor).cacheKey() == actual.cacheKey()


def test_missing_full_display_image_uses_original():
    source = QImage(513, 399, QImage.Format_ARGB32)
    source.fill(0x80336699)
    owner = SimpleNamespace(_static_source_qimage=source, _static_mipmap_pixmaps={})
    actual = ImageViewer._get_static_mipmap_pixmap(owner, 4)
    expected = QPixmap.fromImage(source.scaled(128, 100, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    assert actual.toImage() == expected.toImage()
