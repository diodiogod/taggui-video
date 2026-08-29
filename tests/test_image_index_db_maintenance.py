import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.utils.image_index_db import ImageIndexDB


def test_maintenance_preserves_extreme_video_dimensions(tmp_path):
    video_path = tmp_path / "portrait.mp4"
    image_path = tmp_path / "suspicious.png"
    video_path.write_bytes(b"video")
    image_path.write_bytes(b"image")

    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")

    try:
        database.bulk_insert_files([video_path, image_path], tmp_path)
        database.update_image_dimensions(video_path.name, 720, 5120)
        database.update_image_dimensions(image_path.name, 720, 5120)

        database.run_maintenance(tmp_path)

        video = database.get_image_by_id(database.get_image_id(video_path.name))
        image = database.get_image_by_id(database.get_image_id(image_path.name))
        assert (video["width"], video["height"]) == (720, 5120)
        assert (image["width"], image["height"]) == (None, None)
    finally:
        database.close()
