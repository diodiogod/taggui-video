from pathlib import Path
from types import SimpleNamespace
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from models.image_list_model import ImageListModel


def test_refresh_rebuilds_current_filter_instead_of_installing_old_pages(tmp_path):
    applied, queries = [], []
    def count(**kwargs):
        queries.append(kwargs)
        return 7
    model = SimpleNamespace(
        _new_media_refresh_generation=1, _page_load_generation=8,
        _directory_path=tmp_path, _db=SimpleNamespace(count=count),
        _active_load_options=None, _filter_sql='is_video = 1', _filter_bindings=(),
        _reload_paginated_model_after_db_update=lambda **kwargs: applied.append(kwargs) or [0],
    )
    result = dict(supported=True, generation=1, page_generation=7,
                  directory_path=str(tmp_path), new_total=20,
                  pages_to_reload=[0], preloaded_pages={0: ['old-sort-image']})
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert applied == [dict(new_total=7, preloaded_pages={})]
    assert queries == [dict(filter_sql='is_video = 1', bindings=())]
    assert result['view_changed_during_refresh']
    applied.clear()
    queries.clear()
    result.pop('view_changed_during_refresh')
    result['page_generation'] = 8
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert applied == [dict(new_total=20, preloaded_pages={0: ['old-sort-image']})]
    assert queries == []  # An unchanged view keeps the prepared worker result.
    applied.clear()
    result['directory_path'] = str(tmp_path / 'previous')
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert result['stale'] and applied == []


def test_refresh_does_not_reinstall_pages_evicted_since_scan_started():
    installed, loaded = [], []
    model = SimpleNamespace(
        _paginated_mode=True, PAGE_SIZE=1000, _pages={14: ['visible']},
        _page_load_order=[14], _page_load_lock=threading.Lock(),
        _advance_page_load_generation=lambda: None,
        _load_images_from_db=lambda page: (loaded.append(page) or ['fresh'], []),
        beginResetModel=lambda: None, endResetModel=lambda: None,
        _store_page=lambda page, images: installed.append((page, images)),
        total_count_changed=SimpleNamespace(emit=lambda count: None),
        _emit_paginated_layout_refresh=lambda: None,
        _start_paginated_enrichment=lambda **kwargs: None,
    )
    pages = ImageListModel._reload_paginated_model_after_db_update(
        model, new_total=27000,
        preloaded_pages={0: ['old-window'], 1: ['old-window'], 14: ['prepared']},
    )
    assert pages == [14]
    assert installed == [(14, ['prepared'])]
    assert loaded == []
