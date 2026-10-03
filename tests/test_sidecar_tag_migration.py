import sys
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.utils.image_index_db import ImageIndexDB
from taggui.utils import image_index_db as index_db_module


def rewrite_sidecar(path, text):
    previous = path.stat()
    path.write_text(text, encoding="utf-8")
    # Reconciliation deliberately tolerates 1ms mtime differences. Advance a
    # temporary file explicitly instead of depending on disk/runner speed.
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000))


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

    rewrite_sidecar(media_b.with_suffix(".txt"), "new5555")
    updated = db.reconcile_tags_for_relative_paths(
        tmp_path,
        ["b.webp"],
        ", ",
        batch_size=10,
    )

    assert updated == 1
    # Equal counts have no public tie-order contract.
    assert {entry['tag']: entry['count'] for entry in db.get_all_tags()} == {
        'test': 1, 'new5555': 1,
    }
    assert db.get_tags_for_image(db.get_image_id("a.png")) == ["test"]
    assert db.get_tags_for_image(db.get_image_id("b.webp")) == ["new5555"]


def test_reconcile_tags_incremental_resumes_from_cursor(tmp_path, monkeypatch):
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

    rewrite_sidecar(media_c.with_suffix(".txt"), "updated-three")

    # batch_size limits each SQL fetch; max_seconds limits the whole call.
    # Exhaust the time budget after one fetch to exercise cursor restoration.
    with monkeypatch.context() as clock_patch:
        ticks = iter((0.0, 0.0, 5.0))
        clock_patch.setattr(index_db_module, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
        updated_first, processed_first, wrapped_first = db.reconcile_tags_incremental(
            tmp_path, ", ", batch_size=2, max_seconds=5.0,
        )
    assert updated_first == 0
    assert processed_first == 2
    assert wrapped_first is False
    assert db.get_meta_value(db.TAG_RECONCILE_LAST_ID_KEY) == str(db.get_image_id('b.png'))

    updated_second, processed_second, wrapped_second = db.reconcile_tags_incremental(
        tmp_path,
        ", ",
        batch_size=2,
        max_seconds=5.0,
    )
    assert updated_second == 1
    assert processed_second == 1
    assert wrapped_second is True
    assert db.get_meta_value(db.TAG_RECONCILE_LAST_ID_KEY) == '0'
    assert db.get_tags_for_image(db.get_image_id("c.png")) == ["updated-three"]


def test_incremental_reconciliation_can_process_multiple_batches_in_budget(tmp_path):
    media = [tmp_path / f'{i}.png' for i in range(3)]
    for path in media:
        path.write_bytes(b'')
        path.with_suffix('.txt').write_text('old', encoding='utf-8')
    db = ImageIndexDB(tmp_path)
    db.bulk_insert_files(media, tmp_path)
    db.migrate_tags_from_sidecars(tmp_path, ', ', batch_size=10, max_seconds=5.0)
    rewrite_sidecar(media[-1].with_suffix('.txt'), 'new')

    updated, processed, wrapped = db.reconcile_tags_incremental(
        tmp_path, ', ', batch_size=2, max_seconds=5.0,
    )

    assert (updated, processed, wrapped) == (1, 3, True)
    assert db.get_tags_for_image(db.get_image_id(media[-1].name)) == ['new']
