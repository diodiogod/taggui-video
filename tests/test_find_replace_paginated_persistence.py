import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.models.image_list_model import ImageListModel


class _StubDb:
    def __init__(self):
        self.file_matches = ["sample.png"]
        self.all_paths = ["sample.png"]
        self.image_ids = {"sample.png": 7}
        self.tags_for_image = {}
        self.added_tags = []
        self.txt_mtimes = {}

    def get_files_matching_tag_text(self, text, use_regex=False):
        return list(self.file_matches)

    def get_image_id(self, rel_path):
        return self.image_ids.get(rel_path)

    def get_all_paths(self):
        return list(self.all_paths)

    def set_tags_for_image(self, image_id, tags):
        self.tags_for_image[image_id] = list(tags)

    def add_tag_to_image(self, image_id, tag):
        self.added_tags.append((image_id, tag))

    def set_txt_sidecar_mtime(self, image_id, mtime):
        self.txt_mtimes[image_id] = mtime


def _build_model(tmp_path: Path):
    model = ImageListModel.__new__(ImageListModel)
    model._db = _StubDb()
    model._directory_path = tmp_path
    model.tag_separator = ", "
    model.images = []
    model.undo_stack = deque()
    model.redo_stack = []
    model._pages = {}
    model._page_load_order = []
    model.modelReset = type("_Signal", (), {"emit": lambda self: None})()
    model.update_undo_and_redo_actions_requested = type(
        "_Signal", (), {"emit": lambda self: None})()
    return model


def test_find_and_replace_paginated_writes_txt_and_db(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("alpha test, beta", encoding="utf-8")

    model = _build_model(tmp_path)

    affected = model._find_and_replace_paginated("test", "replacedtest", False)

    assert affected == 1
    assert txt_path.read_text(encoding="utf-8") == "alpha replacedtest, beta"
    assert model._db.tags_for_image[7] == ["alpha replacedtest", "beta"]
    assert 7 in model._db.txt_mtimes


def test_find_and_replace_paginated_handles_empty_result(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("test", encoding="utf-8")

    model = _build_model(tmp_path)

    affected = model._find_and_replace_paginated("test", "", False)

    assert affected == 1
    assert txt_path.read_text(encoding="utf-8") == ""
    assert model._db.tags_for_image[7] == []
    assert model._db.added_tags == [(7, "__no_tags__")]


def test_remove_duplicate_tags_paginated_writes_txt_and_db(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("alpha, alpha, beta", encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    removed = model.remove_duplicate_tags()

    assert removed == 1
    assert txt_path.read_text(encoding="utf-8") == "alpha, beta"
    assert model._db.tags_for_image[7] == ["alpha", "beta"]


def test_remove_duplicate_tags_paginated_preserves_empty_sidecar_entries(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("arms raised4, alpha, beta, beta,  ,  a", encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    removed = model.remove_duplicate_tags()

    assert removed == 1
    assert txt_path.read_text(encoding="utf-8") == "arms raised4, alpha, beta,  ,  a"
    assert model._db.tags_for_image[7] == ["arms raised4", "alpha", "beta", "a"]


def test_sort_tags_alphabetically_paginated_writes_txt_and_db(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("beta, alpha, gamma", encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    model.sort_tags_alphabetically(do_not_reorder_first_tag=False)

    assert txt_path.read_text(encoding="utf-8") == "alpha, beta, gamma"
    assert model._db.tags_for_image[7] == ["alpha", "beta", "gamma"]


def test_remove_duplicate_tags_paginated_undo_restores_txt_and_db(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("alpha, alpha, beta", encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    removed = model.remove_duplicate_tags()
    assert removed == 1
    assert txt_path.read_text(encoding="utf-8") == "alpha, beta"

    model.undo_stack[-1].should_ask_for_confirmation = False
    model.restore_history_tags(is_undo=True)

    assert txt_path.read_text(encoding="utf-8") == "alpha, alpha, beta"
    assert model._db.tags_for_image[7] == ["alpha", "alpha", "beta"]


def test_remove_empty_tags_paginated_cleans_raw_blank_sidecar_entries(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    txt_path.write_text("arms raised4, alpha, beta, beta,  ,  a", encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    removed = model.remove_empty_tags()

    assert removed == 1
    assert txt_path.read_text(encoding="utf-8") == "arms raised4, alpha, beta, beta, a"
    assert model._db.tags_for_image[7] == [
        "arms raised4", "alpha", "beta", "beta", "a"
    ]


def test_remove_empty_tags_paginated_undo_restores_raw_sidecar_text(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"")
    txt_path = image_path.with_suffix(".txt")
    original_text = "arms raised4, alpha, beta, beta,  ,  a"
    txt_path.write_text(original_text, encoding="utf-8")

    model = _build_model(tmp_path)
    model._paginated_mode = True
    model._reload_loaded_pages_after_paginated_tag_change = lambda: None

    removed = model.remove_empty_tags()
    assert removed == 1
    assert txt_path.read_text(encoding="utf-8") == "arms raised4, alpha, beta, beta, a"

    model.undo_stack[-1].should_ask_for_confirmation = False
    model.restore_history_tags(is_undo=True)

    assert txt_path.read_text(encoding="utf-8") == original_text
    assert model._db.tags_for_image[7] == [
        "arms raised4", "alpha", "beta", "beta", "a"
    ]
