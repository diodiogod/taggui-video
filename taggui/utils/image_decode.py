"""Still-image decoding without scene/model/index access from a worker."""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImageReader

from utils.media_file_lock import get_media_file_lock


@dataclass(frozen=True)
class DecodedImage:
    image: object
    requested_path: Path
    resolved_path: Path
    signature: tuple | None


def decode_image(path, cancelled):
    path = Path(path)
    if cancelled.is_set():
        return None
    with get_media_file_lock(path):
        try:
            before = path.stat()
            signature = (before.st_mtime_ns, before.st_size)
        except OSError:
            signature = None  # A previously repaired sibling can still load.
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        reader.setDecideFormatFromContent(True)
        image = reader.read()
        resolved = path
        if image.isNull() and not cancelled.is_set():
            from models.image_list_model import fallback_decode_qimage
            image, _, resolved = fallback_decode_qimage(path)
        if cancelled.is_set():
            return None
        if image is None or image.isNull():
            raise OSError(reader.errorString() or f'Cannot read {path.name}')
        if signature is not None:
            after = path.stat()
            if signature != (after.st_mtime_ns, after.st_size):
                raise OSError('Image changed while it was being read; select it again to reload')
        return DecodedImage(image, path, resolved, signature)
