import json
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest

from models.image_list_model import ImageListModel


def cache_model():
    return SimpleNamespace(_sidecar_meta_cache={},
        _sidecar_meta_cache_lock=threading.Lock(), _sidecar_meta_cache_limit=2048)


def test_workflow_cache_keeps_negative_result_without_nested_objects(tmp_path, monkeypatch):
    model = cache_model()
    path = tmp_path / 'image.json'
    workflow = {'version': .4, 'nodes': [{'inputs': [1, 2, 3]} for _ in range(1000)]}
    path.write_text(json.dumps(workflow), encoding='utf-8')
    read = ImageListModel._read_cached_sidecar_meta
    assert read(model, path) is None
    assert model._sidecar_meta_cache[str(path)][2] is None
    original_open = Path.open
    def fail_reread(self, *args, **kwargs):
        if self == path:
            raise AssertionError('Unchanged negative cache entry was reparsed')
        return original_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_reread)
    assert read(model, path) is None


def test_changed_legacy_sidecar_recovers_all_taggui_metadata(tmp_path):
    model = cache_model()
    path = tmp_path / 'image.json'
    path.write_text('{"version": 0.4}', encoding='utf-8')
    read = ImageListModel._read_cached_sidecar_meta
    assert read(model, path) is None
    metadata = {'version': 1, 'crop': [1, 2, 30, 40], 'rating': .8,
        'markings': [{'label': 'test', 'rect': [1, 2, 3, 4]}],
        'caption_workspace': {'version': 1, 'entries': []},
        'viewer_loop_markers': {'main': {'loop_start_frame': 1, 'loop_end_frame': 8}},
        'future_field': {'keep': [1, 2]}}
    path.write_text(json.dumps(metadata), encoding='utf-8')
    assert read(model, path) == metadata
    assert read(model, path) is model._sidecar_meta_cache[str(path)][2]


@pytest.mark.parametrize('suffix', ['.json', '.taggui.json'])
@pytest.mark.parametrize('text,expected', [
    ('{"nested":{"version":1},"version":0.4}', None),
    ('{"version":1,"version":0.4}', None),
    ('{"version":0.4,"version":1,"label":"café"}', {'version': 1, 'label': 'café'}),
    ('{"nested":{"version":0.4},"vers\\u0069on":1}', {'nested': {'version': .4}, 'version': 1}),
    ('[{"version":1}]', None),
    ('1', None),
    ('{"version":1,broken}', None),
])
def test_metadata_schema_and_json_semantics_are_preserved(tmp_path, suffix, text, expected):
    path = tmp_path / ('image' + suffix)
    path.write_text(text, encoding='utf-8')
    assert ImageListModel._read_cached_sidecar_meta(cache_model(), path) == expected
    assert path.read_text(encoding='utf-8') == text


def test_workflow_export_still_uses_original_json_after_negative_cache(tmp_path):
    from widgets.image_list_view_interaction_mixin import ImageListViewInteractionMixin

    media_path = tmp_path / 'image.png'
    workflow_path = media_path.with_suffix('.json')
    workflow_text = json.dumps({'version': .4, 'nodes': [{'id': 1, 'inputs': [2, 3]}]})
    workflow_path.write_text(workflow_text, encoding='utf-8')
    assert ImageListModel._read_cached_sidecar_meta(cache_model(), workflow_path) is None
    view = SimpleNamespace(_drag_export_mode=lambda: 'workflow_smart')
    view._workflow_sidecar_drag_path_for_image_path = lambda path: (
        ImageListViewInteractionMixin._workflow_sidecar_drag_path_for_image_path(view, path)
    )
    assert ImageListViewInteractionMixin._external_drag_path_for_image_path(view, media_path) == workflow_path
    assert workflow_path.read_text(encoding='utf-8') == workflow_text

    # Legacy TagGUI metadata is still excluded from workflow export.
    workflow_path.write_text('{"version":1,"crop":[1,2,3,4]}', encoding='utf-8')
    assert ImageListViewInteractionMixin._external_drag_path_for_image_path(view, media_path) == media_path
