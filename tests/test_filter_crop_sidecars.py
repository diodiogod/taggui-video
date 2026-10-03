import json
from types import SimpleNamespace

import pytest

from utils.image_index_db import ImageIndexDB
from utils import json_sidecar_reader


@pytest.mark.parametrize('suffix', ['.json', '.taggui.json'])
def test_crop_filter_keeps_legacy_and_dedicated_metadata(tmp_path, suffix):
    owner = SimpleNamespace(_directory_path=tmp_path, _filter_crop_cache={})
    path = tmp_path / ('image' + suffix)
    path.write_text(json.dumps({'version': 1, 'nodes': [], 'state': {},
                                'crop': [20, 30, -10, -15]}), encoding='utf-8')
    assert ImageIndexDB._read_filter_crop(owner, 'image.png') == (10, 15, 10, 15)
    path.write_text(json.dumps({'version': 1, 'crop': [1, 2, 300, 400]}), encoding='utf-8')
    assert ImageIndexDB._read_filter_crop(owner, 'image.png') == (1, 2, 300, 400)


def test_foreign_workflow_is_reduced_and_rejection_shared_across_readers(tmp_path, monkeypatch):
    path = tmp_path / 'image.json'
    path.write_text(json.dumps({'version': 1, 'nodes': [{'nested': {'values': [1, 2, 3]}}],
                                'state': {}}), encoding='utf-8')
    original = json_sidecar_reader.json.loads
    calls = []

    def tracked(text, **kwargs):
        calls.append(kwargs)
        return original(text, **kwargs)

    monkeypatch.setattr(json_sidecar_reader.json, 'loads', tracked)
    for _ in range(2):
        owner = SimpleNamespace(_directory_path=tmp_path, _filter_crop_cache={})
        assert ImageIndexDB._read_filter_crop(owner, 'image.png') is None
    assert len(calls) == 1
    assert 'object_hook' in calls[0]
    path.write_text(json.dumps({'version': 1, 'crop': [1, 2, 30, 40]}), encoding='utf-8')
    owner = SimpleNamespace(_directory_path=tmp_path, _filter_crop_cache={})
    assert ImageIndexDB._read_filter_crop(owner, 'image.png') == (1, 2, 30, 40)


def test_invalid_preferred_sidecar_does_not_fall_back_to_legacy_crop(tmp_path):
    (tmp_path / 'image.json').write_text('{"version":1,"crop":[1,2,3,4]}', encoding='utf-8')
    (tmp_path / 'image.taggui.json').write_text('{broken', encoding='utf-8')
    owner = SimpleNamespace(_directory_path=tmp_path, _filter_crop_cache={})
    assert ImageIndexDB._read_filter_crop(owner, 'image.png') is None
