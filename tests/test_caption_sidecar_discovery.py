"""Selection-side caption discovery must not fully decode generator graphs."""
import json
from pathlib import Path

import pytest

from utils import json_sidecar_reader as reader
from utils.caption_annotations import load_caption_workspace
from utils.ideogram_caption import (
    IdeogramCaptionError, discover_ideogram_caption,
)


@pytest.fixture(autouse=True)
def clear_classifications():
    reader._negative.clear()
    yield
    reader._negative.clear()


@pytest.mark.parametrize('version', [.4, 1])
def test_selection_readers_reduce_workflows_and_skip_repeat_reads(tmp_path, monkeypatch, version):
    media = tmp_path / 'image.png'
    path = media.with_suffix('.json')
    text = json.dumps({'version': version, 'state': {},
                       'nodes': [{'id': i, 'inputs': {'x': [1, 2]}} for i in range(1000)]})
    path.write_text(text, encoding='utf-8')
    loads = json.loads
    calls = []

    def only_reduced(text, **kwargs):
        assert kwargs.get('object_hook') is not None, 'Foreign graph fully decoded'
        calls.append(1)
        return loads(text, **kwargs)

    monkeypatch.setattr(json, 'loads', only_reduced)
    assert load_caption_workspace(media) is None
    assert discover_ideogram_caption(media) is None
    assert len(calls) == 2
    assert load_caption_workspace(media) is None
    assert discover_ideogram_caption(media) is None
    assert len(calls) == 2
    assert path.read_text(encoding='utf-8') == text


def test_negative_classification_is_schema_specific_and_preserves_legacy_fields(tmp_path):
    media = tmp_path / 'image.png'
    path = media.with_suffix('.json')
    path.write_text(json.dumps({'version': 1, 'caption_workspace': {
        'version': 1, 'entries': [{'text': 'cat', 'excluded': True, 'needs_review': True}]
    }}), encoding='utf-8')
    assert discover_ideogram_caption(media) is None
    assert load_caption_workspace(media) == [
        {'text': 'cat', 'excluded': True, 'needs_review': True,
         'direction_reviewed_phrases': []}]
    path.write_text(json.dumps({'compositional_deconstruction': {
        'background': 'white', 'elements': []}}), encoding='utf-8')
    assert load_caption_workspace(media) is None
    assert discover_ideogram_caption(media).compositional_background == 'white'


def test_new_preferred_sidecars_bypass_legacy_rejections(tmp_path):
    media = tmp_path / 'image.png'
    media.with_suffix('.json').write_text('{"nodes":[]}', encoding='utf-8')
    assert load_caption_workspace(media) is None
    assert discover_ideogram_caption(media) is None
    media.with_suffix('.ideogram.json').write_text('{"bad":true}', encoding='utf-8')
    with pytest.raises(IdeogramCaptionError):
        discover_ideogram_caption(media)
    media.with_suffix('.taggui.json').write_text(json.dumps({
        'version': 1, 'caption_workspace': {'version': 1, 'entries': [{'text': 'new'}]}
    }), encoding='utf-8')
    assert load_caption_workspace(media)[0]['text'] == 'new'


@pytest.mark.parametrize('text', [
    '[{"compositional_deconstruction":{"background":"x","elements":[]}}]',
    '{"nested":{"compositional_deconstruction":{"background":"x","elements":[]}}}',
    '{"compositional_deconstruction":{},"compositional_deconstruction":null}',
    '{"compositional_deconstruction":{"background":1,"elements":[]}}',
    '{broken',
])
def test_non_caption_roots_and_malformed_documents_remain_ignored(tmp_path, text):
    media = tmp_path / 'image.png'
    media.with_suffix('.json').write_text(text, encoding='utf-8')
    assert discover_ideogram_caption(media) is None


def test_escaped_key_and_last_duplicate_object_keep_caption_compatibility(tmp_path):
    media = tmp_path / 'image.png'
    media.with_suffix('.json').write_text(
        '{"compositional_deconstruction":null,"compositional_deconstr\\u0075ction":'
        '{"background":"café","elements":[]}}', encoding='utf-8')
    assert discover_ideogram_caption(media).compositional_background == 'café'


def test_rejection_cache_is_bounded_and_evicted_files_are_reclassified(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, '_NEGATIVE_LIMIT', 2)
    paths = [tmp_path / f'{i}.json' for i in range(3)]
    for path in paths:
        path.write_text('{"nodes":[]}', encoding='utf-8')
        assert discover_ideogram_caption(path.with_suffix('.png')) is None
    assert len(reader._negative) == 2
    reads = []
    read = Path.read_text

    def count_read(path, *args, **kwargs):
        reads.append(path)
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', count_read)
    assert discover_ideogram_caption(paths[2].with_suffix('.png')) is None
    assert reads == []
    assert discover_ideogram_caption(paths[0].with_suffix('.png')) is None
    assert reads == [paths[0]]


def test_change_during_classification_does_not_cache_the_new_file(tmp_path, monkeypatch):
    media = tmp_path / 'image.png'
    path = media.with_suffix('.json')
    path.write_text('{"nodes":[]}', encoding='utf-8')
    read = Path.read_text

    def change_after_read(path, *args, **kwargs):
        text = read(path, *args, **kwargs)
        path.write_text('{"compositional_deconstruction":{"background":"new","elements":[]}}',
                        encoding='utf-8')
        return text

    monkeypatch.setattr(Path, 'read_text', change_after_read)
    assert discover_ideogram_caption(media) is None
    assert len(reader._negative) == 0
    monkeypatch.setattr(Path, 'read_text', read)
    assert discover_ideogram_caption(media).compositional_background == 'new'
