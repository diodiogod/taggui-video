import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.utils.image_index_db import ImageIndexDB


def test_migrate_tags_from_sidecars_backfills_missing_db_rows(tmp_path):
    media_a = tmp_path / "a.png"
    media_b = tmp_path / "b.webp"
    media_c = tmp_path / "c.jpg"
    for path in (media_a, media_b, media_c):
        path.write_bytes(b"")

    media_a.with_suffix(".txt").write_text("test", encoding="utf-8")
    media_b.with_suffix(".txt").write_text("test, one", encoding="utf-8")

    db = ImageIndexDB(tmp_path)
    db.bulk_insert_files([media_a, media_b, media_c], tmp_path)

    assert db.get_all_tags() == []

    migrated, scanned, done = db.migrate_tags_from_sidecars(
        tmp_path,
        ", ",
        batch_size=10,
        max_seconds=5.0,
    )

    assert migrated == 2
    assert scanned == 2
    assert done is True
    assert db.get_all_tags() == [
        {"tag": "test", "count": 2},
        {"tag": "one", "count": 1},
    ]
    assert sorted(db.get_files_with_tag("test")) == ["a.png", "b.webp"]

    image_a_id = db.get_image_id("a.png")
    image_b_id = db.get_image_id("b.webp")
    image_c_id = db.get_image_id("c.jpg")

    assert db.get_tags_for_image(image_a_id) == ["test"]
    assert db.get_tags_for_image(image_b_id) == ["test", "one"]
    assert db.get_tags_for_image(image_c_id) == []

    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT txt_sidecar_mtime FROM images WHERE file_name = ?",
        ("a.png",),
    )
    assert cursor.fetchone()[0] is not None
    cursor.execute(
        "SELECT value FROM meta WHERE key = ?",
        (db.TAG_MIGRATION_DONE_KEY,),
    )
    assert cursor.fetchone()[0] == "1"

    migrated_again, scanned_again, done_again = db.migrate_tags_from_sidecars(
        tmp_path,
        ", ",
        batch_size=10,
        max_seconds=5.0,
    )
    assert (migrated_again, scanned_again, done_again) == (0, 0, True)


def test_reconcile_tags_for_relative_paths_refreshes_specific_sidecar(tmp_path):
    media_a = tmp_path / "a.png"
    media_b = tmp_path / "b.webp"
    for path in (media_a, media_b):
        path.write_bytes(b"")

    media_a.with_suffix(".txt").write_text("test", encoding="utf-8")
    media_b.with_suffix(".txt").write_text("test", encoding="utf-8")

    db = ImageIndexDB(tmp_path)
    db.bulk_insert_files([media_a, media_b], tmp_path)
    db.migrate_tags_from_sidecars(tmp_path, ", ", batch_size=10, max_seconds=5.0)

    media_b.with_suffix(".txt").write_text("new5555", encoding="utf-8")
    updated = db.reconcile_tags_for_relative_paths(
        tmp_path,
        ["b.webp"],
        ", ",
        batch_size=10,
    )

    assert updated == 1
    assert db.get_all_tags() == [
        {"tag": "test", "count": 1},
        {"tag": "new5555", "count": 1},
    ]
    assert db.get_tags_for_image(db.get_image_id("a.png")) == ["test"]
    assert db.get_tags_for_image(db.get_image_id("b.webp")) == ["new5555"]


def test_reconcile_tags_incremental_resumes_from_cursor(tmp_path):
    media_a = tmp_path / "a.png"
    media_b = tmp_path / "b.png"
    media_c = tmp_path / "c.png"
    for path in (media_a, media_b, media_c):
        path.write_bytes(b"")

    media_a.with_suffix(".txt").write_text("one", encoding="utf-8")
    media_b.with_suffix(".txt").write_text("two", encoding="utf-8")
    media_c.with_suffix(".txt").write_text("three", encoding="utf-8")

    db = ImageIndexDB(tmp_path)
    db.bulk_insert_files([media_a, media_b, media_c], tmp_path)
    db.migrate_tags_from_sidecars(tmp_path, ", ", batch_size=10, max_seconds=5.0)

    media_c.with_suffix(".txt").write_text("updated-three", encoding="utf-8")

    updated_first, processed_first, wrapped_first = db.reconcile_tags_incremental(
        tmp_path,
        ", ",
        batch_size=2,
        max_seconds=5.0,
    )
    assert updated_first == 0
    assert processed_first == 2
    assert wrapped_first is False

    updated_second, processed_second, wrapped_second = db.reconcile_tags_incremental(
        tmp_path,
        ", ",
        batch_size=2,
        max_seconds=5.0,
    )
    assert updated_second == 1
    assert processed_second == 1
    assert wrapped_second is True
    assert db.get_tags_for_image(db.get_image_id("c.png")) == ["updated-three"]
