"""Folder discovery may retry after write failures and must preserve newer indexes."""
import sqlite3

import pytest

from utils.image_index_db import DB_VERSION, ImageIndexDB


@pytest.mark.parametrize('version,legacy_location', [(DB_VERSION + 1, False),
                                                   (DB_VERSION + 1, True),
                                                   (10, False)])
def test_index_version_preserves_existing_review_state(tmp_path, version, legacy_location):
    db = ImageIndexDB(tmp_path)
    with db.conn:
        db.conn.execute(
            "INSERT INTO images(file_name,is_video,mtime,rating,love) VALUES('keep.png',0,1,.8,1)"
        )
        db.conn.execute("UPDATE meta SET value=? WHERE key='version'", (str(version),))
    db.close()
    expected_path = db.db_path
    if legacy_location:
        expected_path = db.legacy_db_path
        db.db_path.rename(expected_path)

    reopened = ImageIndexDB(tmp_path)
    try:
        if version == DB_VERSION + 1:
            assert reopened.schema_error and reopened.conn is None
            assert not reopened._ensure_connection()
        else:
            assert reopened.schema_error is None
    finally:
        reopened.close()

    assert expected_path.exists()
    conn = sqlite3.connect(expected_path)
    try:
        assert conn.execute("SELECT value FROM meta WHERE key='version'").fetchone() == (
            str(max(version, DB_VERSION)),
        )
        assert conn.execute('SELECT file_name,rating,love FROM images').fetchall() == [
            ('keep.png', .8, 1),
        ]
    finally:
        conn.close()


def test_failed_reconciliation_preserves_paths_tags_and_signatures_for_retry(tmp_path):
    (tmp_path / 'old.png').touch()
    (tmp_path / 'added.png').touch()
    db = ImageIndexDB(tmp_path)
    try:
        assert db.apply_directory_path_changes(['old.png'], [], {'': 1.0}) == (1, 0)
        old_id = db.get_image_id('old.png')
        db.add_tag_to_image(old_id, 'existing')
        with db.conn:
            db.conn.execute("""
                CREATE TRIGGER reject_file BEFORE INSERT ON images
                WHEN NEW.file_name = 'added.png'
                BEGIN SELECT RAISE(ABORT, 'simulated insert failure'); END
            """)
        with pytest.raises(sqlite3.IntegrityError, match='simulated insert failure'):
            db.apply_directory_path_changes(['added.png'], ['old.png'], {'': 2.0})
        assert db.get_all_paths() == ['old.png']
        assert db.get_tags_for_image(old_id) == ['existing']
        assert db.get_directory_signatures() == {'': 1.0}
        with db.conn:
            db.conn.execute('DROP TRIGGER reject_file')

        assert db.apply_directory_path_changes(['added.png'], ['old.png'], {'': 2.0}) == (1, 1)
        assert db.get_all_paths() == ['added.png']
        assert db.get_directory_signatures() == {'': 2.0}
        assert db.apply_directory_path_changes(['added.png'], ['old.png'], {'': 2.0}) == (0, 0)
    finally:
        db.close()
