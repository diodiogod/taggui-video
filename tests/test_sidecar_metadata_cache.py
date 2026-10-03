import json
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest

from models.image_list_model import ImageListModel
from utils.sidecar_metadata_cache import SidecarMetadataCache


def cache_model():
    return SimpleNamespace(_sidecar_meta_cache=SidecarMetadataCache(),
        _sidecar_meta_cache_lock=threading.Lock())


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


def test_workflow_classifications_do_not_evict_taggui_metadata():
    cache = SidecarMetadataCache(positive_limit=2, negative_limit=4)
    metadata = {'version': 1, 'crop': [1, 2, 3, 4]}
    cache['owned'] = (1.0, 100, metadata)
    for i in range(10):
        cache[str(i)] = (1.0, 500000, None)
    assert cache['owned'][2] is metadata
    assert len(cache) == 5
    assert '5' not in cache and '6' in cache


def test_foreign_cache_has_independent_recency_and_signature_byte_limits():
    cache = SidecarMetadataCache(positive_limit=1, negative_limit=2)
    cache['a'] = (1.0, 100, None)
    cache['b'] = (1.0, 100, None)
    assert cache['a'][2] is None
    cache['c'] = (1.0, 100, None)
    assert 'a' in cache and 'b' not in cache
    one_entry_bytes = cache._entry_bytes('a', cache['a'])
    bounded = SidecarMetadataCache(negative_limit=100, negative_byte_limit=one_entry_bytes)
    for key in ('a', 'b', 'c'):
        bounded[key] = (1.0, 100, None)
    assert len(bounded) == 1 and 'c' in bounded
    assert bounded.estimated_negative_bytes == one_entry_bytes
    # A long individual filename is discarded instead of exceeding the budget.
    bounded['x' * 1000] = (1.0, 100, None)
    assert len(bounded) == 0 and bounded.estimated_negative_bytes == 0


def test_metadata_reclassification_and_clear_release_negative_accounting():
    cache = SidecarMetadataCache()
    cache['image.json'] = (1.0, 100, None)
    assert cache.estimated_negative_bytes > 0
    cache['image.json'] = (2.0, 200, {'version': 1})
    assert cache.estimated_negative_bytes == 0
    assert cache['image.json'][2] == {'version': 1}
    cache['image.json'] = (3.0, 300, None)
    assert cache.estimated_negative_bytes > 0
    cache.pop('image.json')
    assert cache.estimated_negative_bytes == 0
    cache['other.json'] = (1.0, 100, None)
    cache.clear()
    assert len(cache) == 0 and cache.estimated_negative_bytes == 0


@pytest.mark.parametrize('version', [.4, 1, 1.0])
def test_comfy_workflow_versions_remain_foreign_and_exportable(tmp_path, version):
    from utils.caption_annotations import load_caption_workspace, save_caption_workspace
    from utils.sidecar import is_taggui_metadata_dict
    from widgets.image_list_view_interaction_mixin import ImageListViewInteractionMixin

    workflow = {'version': version, 'state': {'lastNodeId': 7, 'lastLinkId': 0},
                'nodes': [{'id': 7, 'type': 'KSampler', 'inputs': [{'name': 'model'}]}],
                'links': []}
    path = tmp_path / 'image.json'
    text = json.dumps(workflow)
    path.write_text(text, encoding='UTF-8')
    assert not is_taggui_metadata_dict(workflow)
    model = cache_model()
    assert ImageListModel._read_cached_sidecar_meta(model, path) is None
    assert model._sidecar_meta_cache[str(path)][2] is None
    assert ImageListViewInteractionMixin._workflow_sidecar_drag_path_for_image_path(
        SimpleNamespace(), tmp_path / 'image.png') == path
    assert path.read_text(encoding='UTF-8') == text

    # An actual metadata edit creates our dedicated sidecar without adopting
    # the workflow graph, and the original workflow remains available to drag.
    entries = [{'text': 'caption', 'needs_review': True, 'excluded': False}]
    media_path = tmp_path / 'image.png'
    assert save_caption_workspace(media_path, entries) == (1, 0)
    owned = json.loads(media_path.with_suffix('.taggui.json').read_text(encoding='UTF-8'))
    assert set(owned) == {'version', 'caption_workspace'}
    assert load_caption_workspace(media_path)[0]['text'] == 'caption'
    assert ImageListViewInteractionMixin._workflow_sidecar_drag_path_for_image_path(
        SimpleNamespace(), media_path) == path
    assert path.read_text(encoding='UTF-8') == text


@pytest.mark.parametrize('text,expected', [
    ('{"version":1,"state":{},"nodes":[]}', None),
    ('{"version":1,"state":{},"nodes":[],"rating":0.5,"unknown":"keep"}',
     {'version': 1, 'state': {}, 'nodes': [], 'rating': .5, 'unknown': 'keep'}),
    ('{"version":1,"state":null,"nodes":[]}', {'version': 1, 'state': None, 'nodes': []}),
    ('{"version":1,"state":{},"nodes":{}}', {'version': 1, 'state': {}, 'nodes': {}}),
    ('{"version":{"version":1}}', None),
    ('[{"version":1,"crop":[1,2,3,4]}]', None),
    ('{"nested":{"state":{},"nodes":[],"version":1},"version":1}',
     {'nested': {'state': {}, 'nodes': [], 'version': 1}, 'version': 1}),
])
@pytest.mark.parametrize('suffix', ['.json', '.taggui.json'])
def test_root_workflow_shape_preserves_metadata_compatibility(tmp_path, text, expected, suffix):
    path = tmp_path / ('image' + suffix)
    path.write_text(text, encoding='UTF-8')
    assert ImageListModel._read_cached_sidecar_meta(cache_model(), path) == expected
