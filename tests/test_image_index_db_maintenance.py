import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.utils.image_index_db import DB_VERSION, ImageIndexDB


def test_version_2_cache_rebuilds_before_new_indexes_are_created(tmp_path):
    db_dir = tmp_path / ImageIndexDB.DB_DIR_NAME
    db_dir.mkdir()
    connection = sqlite3.connect(db_dir / ImageIndexDB.DB_FILE_NAME)
    connection.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta (key, value) VALUES ('version', '2');
        CREATE TABLE images (
            file_name TEXT UNIQUE NOT NULL,
            width INTEGER,
            height INTEGER,
            is_video INTEGER NOT NULL,
            video_fps REAL,
            video_duration REAL,
            video_frame_count INTEGER,
            mtime REAL NOT NULL
        );
        CREATE TABLE image_tags (image_id INTEGER NOT NULL, tag TEXT NOT NULL);
        """
    )
    connection.commit()
    connection.close()

    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")

    try:
        assert database.conn is not None
        columns = {
            row["name"]
            for row in database.conn.execute("PRAGMA table_info(images)").fetchall()
        }
        version = database.conn.execute(
            "SELECT value FROM meta WHERE key = 'version'"
        ).fetchone()["value"]

        assert version == str(DB_VERSION)
        assert {"id", "aspect_ratio", "rating", "indexed_at", "thumbnail_cached"} <= columns
    finally:
        database.close()


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
