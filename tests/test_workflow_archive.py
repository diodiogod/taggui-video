"""Real 7-Zip round trips and destructive-operation failure boundaries."""
import json
import os
from pathlib import Path
import threading
from contextlib import contextmanager
from types import SimpleNamespace
import random

import pytest

from utils import workflow_archive as wa


def workflow(version=.4):
    if version == 'api':
        return {'1': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'test'}}}
    payload = {'version': version, 'nodes': [{'id': 1, 'type': 'CLIPTextEncode'}]}
    payload.update({'state': {}} if version == 1 else {'last_node_id': 1, 'last_link_id': 0, 'links': []})
    return payload


def pair(folder, name='image', payload=None):
    (folder / f'{name}.png').write_bytes(b'media')
    path = folder / f'{name}.json'
    path.write_text(json.dumps(workflow() if payload is None else payload), encoding='utf-8')
    return path


@pytest.fixture
def sevenzip():
    try:
        return wa.find_7zip()
    except wa.ArchiveError:
        pytest.skip('7-Zip is required for archive integration tests')


@pytest.mark.parametrize('payload,expected', [
    (workflow(), True), (workflow(1), True), (workflow('api'), True),
    ({'version': 1, 'rating': 4}, False),
    ({**workflow(1), 'crop': [0, 0, 1, 1]}, False),
    ({**workflow(), 'caption_workspace': {}}, False),
    ({'version': 1, 'nodes': []}, False),
    ({'version': .4, 'nodes': [{'id': 1}]}, False),
    ({'prompt': 'not a workflow'}, False), ({}, False), ([], False),
])
def test_only_recognized_unmixed_workflows(payload, expected):
    assert wa.is_workflow(payload) is expected


def test_create_remove_restore_and_drag(sevenzip, tmp_path):
    paths = [pair(tmp_path, name, workflow(version)) for name, version in
             [('image', .4), ('unicode café', 1), ('api', 'api')]]
    originals = {path: path.read_bytes() for path in paths}
    metadata = pair(tmp_path, 'metadata', {'version': 1, 'rating': 5})
    dedicated = tmp_path / 'image.taggui.json'
    dedicated.write_text(json.dumps(workflow()))  # suffix always protects it
    unknown = pair(tmp_path, 'unknown', {'hello': 'world'})
    orphan = tmp_path / 'orphan.json'
    orphan.write_text(json.dumps(workflow()))
    subfolder = tmp_path / 'nested'
    subfolder.mkdir()
    nested = pair(subfolder)
    result = wa.create_archive(tmp_path, {'.png'})
    assert result.archived == 3 and result.removed == 0
    assert all(p.exists() for p in paths)
    result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert result.removed == 3 and result.skipped == 2
    assert all(not p.exists() for p in paths)
    assert all(p.exists() for p in (metadata, dedicated, unknown, orphan, nested))
    cache = wa.WorkflowDragCache()
    for path, data in originals.items():
        media = path.with_suffix('.png')
        assert cache.lookup(media) == (False, None)
        cache.prepare([media])
        ready, extracted = cache.lookup(media)
        assert ready and extracted.read_bytes() == data
    restored = wa.restore_archive(tmp_path)
    assert restored.restored == 3
    assert all(path.read_bytes() == data for path, data in originals.items())
    assert wa.restore_archive(tmp_path).unchanged == 3


def test_update_preserves_old_members_and_rejects_conflicting_version(sevenzip, tmp_path):
    first = pair(tmp_path)
    wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    second = pair(tmp_path, 'new')
    assert wa.create_archive(tmp_path, {'.png'}, remove_originals=True).archived == 2
    archive = tmp_path / wa.ARCHIVE_NAME
    before = archive.read_bytes()
    pair(tmp_path, payload=workflow('api'))
    with pytest.raises(wa.ArchiveError, match='differs'):
        wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert archive.read_bytes() == before and first.exists()
    result = wa.restore_archive(tmp_path)
    assert result.restored == 1 and result.retained == ['image.json'] and second.exists()
    assert json.loads(first.read_bytes()) == workflow('api')


def test_verification_failure_never_publishes_or_removes(sevenzip, tmp_path, monkeypatch):
    original = pair(tmp_path)
    run = wa._run
    def corrupt(args, **kwargs):
        if args[0] == 't':
            Path(args[-1]).write_bytes(b'broken archive')
        return run(args, **kwargs)
    monkeypatch.setattr(wa, '_run', corrupt)
    with pytest.raises(wa.ArchiveError):
        wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert original.exists() and not (tmp_path / wa.ARCHIVE_NAME).exists()
    assert not (tmp_path / '.workflows.7z.lock').exists()


def test_changed_original_is_kept_during_cleanup(sevenzip, tmp_path):
    original = pair(tmp_path)
    def progress(message):
        if message.startswith('Removing'):
            original.write_text('new user edits')
    result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True, progress=progress)
    assert result.removed == 0 and result.retained == ['image.json']
    assert original.read_text() == 'new user edits'


def test_cancel_before_publish_preserves_existing_archive(sevenzip, tmp_path):
    original = pair(tmp_path)
    wa.create_archive(tmp_path, {'.png'})
    archive = tmp_path / wa.ARCHIVE_NAME
    before = archive.read_bytes()
    pair(tmp_path, 'new')
    cancel = threading.Event()
    def progress(message):
        if message.startswith('Verifying'):
            cancel.set()
    with pytest.raises(wa.ArchiveCancelled):
        wa.create_archive(tmp_path, {'.png'}, remove_originals=True, cancel=cancel, progress=progress)
    assert original.exists() and archive.read_bytes() == before


def test_foreign_archive_not_modified_but_drag_supported(sevenzip, tmp_path):
    path = pair(tmp_path)
    archive = tmp_path / wa.ARCHIVE_NAME
    wa._run(['a', '-t7z', str(archive), path.name], cwd=tmp_path)
    before = archive.read_bytes()
    with pytest.raises(wa.ArchiveError, match='not created by TagGUI'):
        wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert archive.read_bytes() == before and path.exists()
    cache = wa.WorkflowDragCache()
    cache.prepare([path.with_suffix('.png')])
    assert cache.lookup(path.with_suffix('.png'))[1].read_bytes() == path.read_bytes()


def test_cache_invalidation_and_missing_member(sevenzip, tmp_path):
    path = pair(tmp_path)
    wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    cache = wa.WorkflowDragCache()
    media = path.with_suffix('.png')
    cache.prepare([media, tmp_path / 'missing.png'])
    assert cache.lookup(media)[0]
    assert cache.lookup(tmp_path / 'missing.png') == (True, None)
    pair(tmp_path, 'new')
    wa.create_archive(tmp_path, {'.png'})
    assert cache.lookup(media) == (False, None)
    cache.prepare([media])
    assert cache.lookup(media)[1].exists()


@pytest.mark.parametrize('name', ['../outside.json', 'C:bad.json', 'x.taggui.json', 'a/b.json', 'NUL.json'])
def test_unsafe_archive_members_rejected_before_extraction(tmp_path, monkeypatch, name):
    monkeypatch.setattr(wa, '_run', lambda *a, **kw: f'Path = {name}\nSize = 2\nAttributes = A\n'.encode())
    with pytest.raises(wa.ArchiveError):
        wa._members(tmp_path / wa.ARCHIVE_NAME)


def test_missing_tool_keeps_originals(tmp_path, monkeypatch):
    original = pair(tmp_path)
    def missing():
        raise wa.ArchiveError('Install 7-Zip')
    monkeypatch.setattr(wa, 'find_7zip', missing)
    with pytest.raises(wa.ArchiveError, match='Install'):
        wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert original.exists()


@pytest.mark.parametrize('change_moved_file', [False, True])
def test_new_save_during_cleanup_is_never_deleted(sevenzip, tmp_path, monkeypatch, change_moved_file):
    original = pair(tmp_path)
    rename = os.rename
    def save_during_move(source, destination):
        rename(source, destination)
        if Path(destination).parent.name.startswith('.workflow-originals-'):
            Path(source).write_text('new save at the original filename')
            if change_moved_file:
                Path(destination).write_text('concurrent edits to the moved original')
    monkeypatch.setattr(os, 'rename', save_during_move)
    result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert original.read_text() == 'new save at the original filename'
    if change_moved_file:
        assert result.removed == 0 and len(result.retained) == 1
        assert (tmp_path / result.retained[0]).read_text() == 'concurrent edits to the moved original'
    else:
        assert result.removed == 1
        assert not list(tmp_path.glob('.workflow-originals-*'))


@pytest.mark.parametrize('cancel_early', [False, True])
def test_large_scan_streams_throttled_progress_before_enumeration_finishes(tmp_path, monkeypatch, cancel_early):
    total = 100_000
    visited = [0]
    updates = []
    cancel = threading.Event()
    real_scandir = os.scandir
    @contextmanager
    def synthetic_scan():
        def entries():
            for number in range(total):
                visited[0] += 1
                yield SimpleNamespace(name=f'unrelated-{number}.txt')
        yield entries()
    def scan(path):
        if not isinstance(path, int) and Path(path) == tmp_path:
            return synthetic_scan()
        return real_scandir(path)
    monkeypatch.setattr(os, 'scandir', scan)
    # Simulate ten seconds of scanning without sleeping or allocating 100k files.
    monkeypatch.setattr(wa, 'time', SimpleNamespace(monotonic=lambda: visited[0] / 10_000))
    def progress(update):
        if str(update).startswith('Scanning folder:'):
            updates.append((visited[0], str(update)))
            if cancel_early and visited[0] >= 2000:
                cancel.set()
    if cancel_early:
        with pytest.raises(wa.ArchiveCancelled):
            wa.create_archive(tmp_path, {'.png'}, cancel=cancel, progress=progress)
        assert visited[0] < total
    else:
        assert wa.create_archive(tmp_path, {'.png'}, progress=progress).archived == 0
        assert visited[0] == total
        assert 20 < len(updates) < 60  # bounded signals, not one per entry
    assert any(0 < count < total and 'Current: unrelated-' in text for count, text in updates)
    assert not (tmp_path / wa.ARCHIVE_NAME).exists()


def test_cleanup_only_does_not_repack_reparse_or_reread_known_sources(sevenzip, tmp_path, monkeypatch):
    paths = [pair(tmp_path, f'image-{i}') for i in range(8)]
    wa.create_archive(tmp_path, {'.png'})
    archive = tmp_path / wa.ARCHIVE_NAME
    before = archive.read_bytes()
    stamp = wa.archive_stamp(archive)
    commands = []
    run, read_bytes = wa._run, Path.read_bytes
    def observed_run(args, **kwargs):
        commands.append(args[0])
        assert args[0] not in ('a', 't')
        return run(args, **kwargs)
    def guarded_read(path):
        assert path not in paths, 'Unchanged source was read again'
        return read_bytes(path)
    monkeypatch.setattr(wa, '_run', observed_run)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    monkeypatch.setattr(wa, '_unpack', lambda *a, **kw: pytest.fail('Full archive extraction'))
    monkeypatch.setattr(wa, '_workflow_bytes', lambda *a: pytest.fail('JSON parsed again'))
    result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert result.removed == 8 and result.reused == 8 and result.added == 0
    assert not result.archive_updated and all(not path.exists() for path in paths)
    assert wa.archive_stamp(archive) == stamp and archive.read_bytes() == before
    assert commands == ['l', 'x']  # headers + manifest only


def test_single_addition_only_stages_and_tests_new_data(sevenzip, tmp_path, monkeypatch):
    old = pair(tmp_path, 'old')
    wa.create_archive(tmp_path, {'.png'})
    new = pair(tmp_path, 'new')
    run, read_bytes = wa._run, Path.read_bytes
    compressed, verified = [], []
    def observed_run(args, **kwargs):
        if args[0] == 'a':
            compressed.append({p.name for p in Path(kwargs['cwd']).iterdir()})
        if args[0] == 't':
            selection = next(arg[3:] for arg in args if arg.startswith('-i@'))
            verified.extend(Path(selection).read_text(encoding='utf-8').splitlines())
        return run(args, **kwargs)
    def guarded_read(path):
        assert path != old, 'Previously indexed workflow was reread'
        return read_bytes(path)
    with monkeypatch.context() as scoped:
        scoped.setattr(wa, '_run', observed_run)
        scoped.setattr(Path, 'read_bytes', guarded_read)
        scoped.setattr(wa, '_unpack', lambda *a, **kw: pytest.fail('Full archive extraction'))
        result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert result.added == 1 and result.reused == 1 and result.removed == 2
    assert compressed == [{'new.json'}, {'new.json', wa.MANIFEST_NAME}]
    assert set(verified) == {'new.json', wa.MANIFEST_NAME}
    assert wa.restore_archive(tmp_path).restored == 2
    assert json.loads(old.read_bytes()) == workflow() == json.loads(new.read_bytes())


def test_legacy_archive_cleanup_hashes_once_without_rebuilding(sevenzip, tmp_path, monkeypatch):
    original = pair(tmp_path)
    digest = wa._digest(original.read_bytes())
    manifest = tmp_path / wa.MANIFEST_NAME
    manifest.write_text(json.dumps({'format': 'taggui-workflows-1', 'sha256': {original.name: digest}}))
    archive = tmp_path / wa.ARCHIVE_NAME
    wa._run(['a', '-t7z', str(archive), original.name, manifest.name], cwd=tmp_path)
    manifest.unlink()
    stamp = wa.archive_stamp(archive)
    reads = []
    original_read = Path.read_bytes
    def observed_read(path):
        if path == original:
            reads.append(path)
        return original_read(path)
    monkeypatch.setattr(Path, 'read_bytes', observed_read)
    monkeypatch.setattr(wa, '_workflow_bytes', lambda *a: pytest.fail('Known workflow reparsed'))
    result = wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    assert reads == [original] and result.removed == 1
    assert not result.archive_updated and wa.archive_stamp(archive) == stamp


def test_real_compression_reports_intermediate_percentages(sevenzip, tmp_path):
    payload = workflow()
    payload['nodes'][0]['widgets_values'] = [random.Random(17).randbytes(6 * 1024 * 1024).hex()]
    pair(tmp_path, payload=payload)
    values = []
    def progress(update):
        if str(update).startswith('Compressing') and getattr(update, 'total', None) == 100:
            values.append(update.completed)
    wa.create_archive(tmp_path, {'.png'}, progress=progress)
    assert values[0] == 0 and values[-1] == 100
    assert any(0 < value < 100 for value in values), values
