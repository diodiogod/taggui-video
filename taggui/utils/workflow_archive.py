"""Conservative, folder-local ComfyUI workflow archives (no Qt or settings I/O)."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from utils.sidecar import _TAGGUI_METADATA_FIELDS, TAGGUI_SIDECAR_SUFFIX

ARCHIVE_NAME = 'workflows.7z'
MANIFEST_NAME = '__taggui_workflows__.json'
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024


class ArchiveProgress(str):
    """Text-compatible progress with an optional known work total."""
    def __new__(cls, message, completed=0, total=None):
        value = super().__new__(cls, message)
        value.completed = completed
        value.total = total
        return value


class _ProgressReporter:
    """Bound queued GUI updates regardless of dataset size or storage speed."""
    def __init__(self, callback):
        self.callback = callback
        self.last_update = float('-inf')

    def update(self, message, completed=0, total=None, *, force=False):
        now = time.monotonic()
        if force or now - self.last_update >= .2:
            self.callback(ArchiveProgress(message, completed, total))
            self.last_update = now


class ArchiveError(RuntimeError):
    pass


class ArchiveCancelled(ArchiveError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ArchiveCancelled('Cancelled. Any completed archive or restored files were kept.')


def find_7zip() -> str:
    for name in ('7zz', '7z', '7za'):
        executable = shutil.which(name)
        if executable:
            return executable
    for root in ('ProgramFiles', 'ProgramFiles(x86)'):
        candidate = Path(os.environ.get(root, 'C:/Program Files')) / '7-Zip' / '7z.exe'
        if candidate.is_file():
            return str(candidate)
    raise ArchiveError('Install 7-Zip to use workflow archives (7z or 7zz on PATH).')


def _run(args, *, cwd=None, cancel=None, output_file=None, output_limit=None,
         progress=None, phase='Processing archive'):
    check_cancel(cancel)
    reporter = _ProgressReporter(progress) if progress is not None else None
    if reporter:
        reporter.update(f'{phase}: 0%', 0, 100, force=True)
    # Separate handles avoid sharing the subprocess's file offset. stderr is
    # polled rather than read by lines: 7-Zip uses carriage returns/backspaces.
    with tempfile.TemporaryDirectory(prefix='taggui-7z-progress-') as directory:
        error_path = Path(directory) / 'stderr'
        with error_path.open('wb') as writer, error_path.open('rb') as reader, subprocess.Popen(
            [find_7zip(), args[0], '-sccUTF-8', '-bsp2' if reporter else '-bd', '-y', *args[1:]],
            cwd=cwd, stdin=subprocess.DEVNULL, stdout=output_file or subprocess.PIPE,
            stderr=writer, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        ) as process:
            tail = b''
            last_percent = -1
            while True:
                try:
                    output, _ = process.communicate(timeout=.1)
                    finished = True
                except subprocess.TimeoutExpired:
                    finished = False
                chunk = reader.read()
                tail = (tail + chunk)[-4000:]
                if reporter and chunk:
                    percentages = re.findall(rb'(?<!\d)(\d{1,3})%', tail)
                    if percentages:
                        percent = min(100, int(percentages[-1]))
                        if percent != last_percent:
                            reporter.update(f'{phase}: {percent}%', percent, 100)
                            last_percent = percent
                too_large = (output_file is not None and output_limit is not None
                             and os.fstat(output_file.fileno()).st_size > output_limit)
                if too_large or cancel is not None and cancel.is_set():
                    if not finished:
                        process.kill()
                    process.communicate()
                    if too_large:
                        raise ArchiveError('Extracted data exceeded the declared archive size.')
                    check_cancel(cancel)
                if finished:
                    break
            if process.returncode:
                raise ArchiveError((tail or output or b'7-Zip failed.').decode('utf-8', errors='replace')[-2000:])
    if reporter:
        reporter.update(f'{phase}: 100%', 100, 100, force=True)
    return output or b''


def is_workflow(payload) -> bool:
    """Recognize graph v0.4/v1 and API exports; never archive mixed TagGUI data.

    Graph structure follows docs.comfy.org/specs/workflow_json and
    workflow_json_0.4. Unknown JSON is deliberately left alone.
    """
    if not isinstance(payload, dict) or not payload or _TAGGUI_METADATA_FIELDS.intersection(payload):
        return False
    nodes = payload.get('nodes')
    if isinstance(nodes, list):
        if not all(isinstance(n, dict) and isinstance(n.get('type'), str)
                   and isinstance(n.get('id'), (int, str)) for n in nodes):
            return False
        return ((payload.get('version') == .4 and isinstance(payload.get('links'), list)
                 and 'last_node_id' in payload and 'last_link_id' in payload)
                or (payload.get('version') == 1 and isinstance(payload.get('state'), dict)))
    return all(isinstance(key, str) and key.isdecimal() and isinstance(node, dict)
               and isinstance(node.get('class_type'), str)
               and isinstance(node.get('inputs'), dict) for key, node in payload.items())


def _workflow_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        return None
    data = path.read_bytes()
    try:
        return data if is_workflow(json.loads(data)) else None
    except (ValueError, UnicodeError, RecursionError):
        return None


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _source_stamp(path):
    try:
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES:
            return [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
    except FileNotFoundError:
        pass
    return None


def _read_member(archive, name, size, cancel=None, progress=None):
    with tempfile.TemporaryFile() as stream:
        _run(['x', '-so', '-spd', '-t7z', str(archive), '--', name], cancel=cancel,
             output_file=stream, output_limit=size, progress=progress, phase='Reading archive index')
        stream.seek(0)
        data = stream.read(size + 1)
    if len(data) != size:
        raise ArchiveError(f'Invalid archived file size: {name}')
    return data


def _read_archive_index(archive, cancel=None, progress=None):
    """Read headers and the small manifest, never all archived workflows."""
    before = archive_stamp(archive)
    members = _members(archive, cancel)
    if MANIFEST_NAME not in members:
        raise ArchiveError('This workflows.7z was not created by TagGUI. It will not be modified.')
    manifest = json.loads(_read_member(archive, MANIFEST_NAME, members[MANIFEST_NAME], cancel, progress))
    hashes = manifest.get('sha256')
    if (manifest.get('format') != 'taggui-workflows-1' or not isinstance(hashes, dict)
            or set(hashes) != set(members) - {MANIFEST_NAME}
            or not all(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest)
                       for digest in hashes.values())):
        raise ArchiveError('Invalid workflow archive index. Original files were kept.')
    sources = manifest.get('sources', {})
    if not isinstance(sources, dict):
        sources = {}
    sources = {name: stamp for name, stamp in sources.items()
               if name in hashes and isinstance(stamp, list) and len(stamp) == 4
               and all(isinstance(value, int) for value in stamp) and stamp[0] == members[name]}
    if archive_stamp(archive) != before:
        raise ArchiveError('Archive changed while reading its index. Please retry.')
    return hashes, sources, {name: size for name, size in members.items() if name != MANIFEST_NAME}


def _copy_archive(source, destination, cancel, reporter):
    total = source.stat().st_size
    copied = 0
    with source.open('rb') as incoming, destination.open('wb') as outgoing:
        while True:
            check_cancel(cancel)
            chunk = incoming.read(4 * 1024 * 1024)
            if not chunk:
                break
            outgoing.write(chunk)
            copied += len(chunk)
            # Percent keeps Qt's signed-int progress range safe for large 7z files.
            percent = int(copied * 100 / max(1, total))
            reporter.update(f'Preparing archive update: {percent}% '
                            f'({copied / 1048576:.1f} / {total / 1048576:.1f} MiB)',
                            percent, 100, force=copied == total)


def _safe_name(name):
    return (isinstance(name, str) and name not in ('', '.', '..')
            and not any(c in name for c in '/\\:*?"<>|')
            and not any(ord(c) < 32 for c in name)
            and not name.endswith((' ', '.'))
            and name.split('.')[0].upper() not in {
                'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)),
                *(f'LPT{i}' for i in range(10))}
            and name.lower().endswith('.json')
            and not name.lower().endswith(TAGGUI_SIDECAR_SUFFIX))


def archive_stamp(path):
    try:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    except FileNotFoundError:
        return None


def _members(archive, cancel=None):
    listing = _run(['l', '-slt', '-ba', '-t7z', str(archive)], cancel=cancel).decode('utf-8')
    members = {}
    seen = set()
    for block in listing.replace('\r\n', '\n').strip().split('\n\n'):
        record = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
        if not record:
            continue
        name = record.get('Path', '')
        attributes = record.get('Attributes', '')
        if (not _safe_name(name) or name.casefold() in seen
                or record.get('Folder') == '+' or record.get('Encrypted') == '+'
                or 'Symbolic Link' in record or 'Hard Link' in record
                or 'Reparse' in record or 'L' in attributes or 'l' in attributes):
            raise ArchiveError('Archive must contain only unique, unencrypted workflow JSON filenames, without folders or links.')
        size = int(record.get('Size', '-1'))
        if not 0 <= size <= MAX_FILE_BYTES:
            raise ArchiveError('Workflow archive entry exceeds the 64 MiB safety limit.')
        members[name] = size
        seen.add(name.casefold())
    if sum(members.values()) > MAX_TOTAL_BYTES:
        raise ArchiveError('Workflow archive exceeds the 4 GiB unpacked safety limit.')
    return members


def _unpack(archive, destination, cancel=None, *, managed=True):
    before = archive_stamp(archive)
    members = _members(archive, cancel)
    if managed and MANIFEST_NAME not in members:
        raise ArchiveError('This workflows.7z was not created by TagGUI. It will not be modified. Rename it before creating a managed archive.')
    files = {}
    # Decode once, in archive member order, to a private stream. Never allow
    # 7-Zip to create archive-controlled paths or links on the filesystem.
    with tempfile.TemporaryFile() as stream:
        total = sum(members.values())
        _run(['x', '-so', '-t7z', str(archive)], cancel=cancel,
             output_file=stream, output_limit=total)
        if os.fstat(stream.fileno()).st_size != total:
            raise ArchiveError('Extracted size does not match the archive listing.')
        stream.seek(0)
        for name, size in members.items():
            check_cancel(cancel)
            data = stream.read(size)
            if name != MANIFEST_NAME:
                if not is_workflow(json.loads(data)):
                    raise ArchiveError(f'Not a recognized ComfyUI workflow: {name}')
                files[name] = _digest(data)
            (destination / name).write_bytes(data)
    if MANIFEST_NAME in members:
        manifest = json.loads((destination / MANIFEST_NAME).read_bytes())
        if (manifest.get('format') != 'taggui-workflows-1'
                or manifest.get('sha256') != files):
            raise ArchiveError('Workflow archive verification failed; original files were kept.')
    if archive_stamp(archive) != before:
        raise ArchiveError('Archive changed during extraction. Please retry.')
    return files


@contextmanager
def _folder_lock(folder):
    path = folder / '.workflows.7z.lock'
    try:
        handle = path.open('x')
    except FileExistsError:
        raise ArchiveError('Another workflow archive operation is active. If TagGUI previously crashed, remove .workflows.7z.lock after checking no operation is running.') from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


@dataclass
class ArchiveResult:
    archived: int = 0
    removed: int = 0
    restored: int = 0
    unchanged: int = 0
    skipped: int = 0
    retained: list[str] = field(default_factory=list)
    source_bytes: int = 0
    archive_bytes: int = 0
    added: int = 0
    reused: int = 0
    archive_updated: bool = False


def _publish_without_replace(source, destination):
    if os.name == 'nt':
        # Windows rename refuses existing targets, including on FAT/exFAT.
        os.rename(source, destination)
    else:
        os.link(source, destination)
        source.unlink()


def _remove_original(path, archive, published_stamp, recovery, source_stamp):
    """Move first, then verify: never unlink a replacement at the source path.

    A crash can leave a recoverable file in .workflow-originals-*, so this
    directory is intentionally not an auto-cleaned TemporaryDirectory.
    """
    if _source_stamp(path) != source_stamp:
        return path.name
    held = recovery / path.name
    os.rename(path, held)
    try:
        held_stamp = _source_stamp(held)
        # Rename can change ctime. Size, mtime and file identity must survive it.
        same = (held_stamp is not None and
                [held_stamp[0], held_stamp[1], held_stamp[3]] ==
                [source_stamp[0], source_stamp[1], source_stamp[3]])
        if (same
                and archive_stamp(archive) == published_stamp):
            held.unlink()
            return None
    except OSError:
        pass
    try:
        _publish_without_replace(held, path)
        return path.name
    except OSError:
        # Another process saved a replacement, or the destination is locked.
        # Keep both versions, and report the recovery path to the user.
        return str(held.relative_to(path.parent))


def create_archive(folder, media_suffixes, *, remove_originals=False, cancel=None, progress=lambda text: None):
    folder = Path(folder).resolve()
    archive = folder / ARCHIVE_NAME
    result = ArchiveResult()
    with _folder_lock(folder), tempfile.TemporaryDirectory(prefix='.workflow-stage-', dir=folder) as temporary:
        staging = Path(temporary)
        inputs = staging / 'inputs'
        inputs.mkdir()
        original_stamp = archive_stamp(archive)
        progress('Reading existing archive index…')
        hashes, sources, sizes = (_read_archive_index(archive, cancel, progress)
                                 if original_stamp else ({}, {}, {}))
        names_by_case = {name.casefold(): name for name in hashes}
        candidates = set()
        reporter = _ProgressReporter(progress)
        reporter.update('Scanning folder: 0 entries visited…', force=True)
        scanned = 0
        # Path.iterdir() on Python 3.12 materializes os.listdir() first. scandir
        # reports work and honors cancellation before enumeration has finished,
        # and reuses directory-entry metadata instead of statting every media.
        with os.scandir(folder) as entries:
            for entry in entries:
                check_cancel(cancel)
                scanned += 1
                media = Path(entry.name)
                if media.suffix.lower() in media_suffixes and entry.is_file(follow_symlinks=False):
                    candidates.add(folder / media.with_suffix('.json'))
                reporter.update(
                    f'Scanning folder: {scanned:,} entries visited; '
                    f'{len(candidates):,} possible workflow JSON files.\nCurrent: {entry.name}')
        reporter.update(
            f'Scan complete: {scanned:,} entries visited; {len(candidates):,} possible workflow JSON files.',
            force=True)
        originals = {}
        additions = []
        total = len(candidates)
        reporter.update(f'Checking accompanying JSON: 0 / {total:,}; 0 workflows found.', 0, total, force=True)
        for checked, path in enumerate(candidates):
            check_cancel(cancel)
            reporter.update(
                f'Checking accompanying JSON: {checked:,} / {total:,}; '
                f'{len(originals):,} workflows found; {result.skipped:,} other JSON skipped.\nCurrent: {path.name}',
                checked, total, force=checked == 0)
            if not _safe_name(path.name) or path.name.casefold() == MANIFEST_NAME.casefold():
                continue
            source_stamp = _source_stamp(path)
            if source_stamp is None:
                continue
            collision = names_by_case.get(path.name.casefold())
            if collision is not None:
                if collision != path.name:
                    raise ArchiveError(f'{path.name} conflicts with the archived filename {collision}.')
                # New manifests remember the source's file identity and times.
                # Older archives require one raw hash comparison, not JSON parsing.
                if sources.get(path.name) != source_stamp:
                    data = path.read_bytes()
                    if _source_stamp(path) != source_stamp:
                        raise ArchiveError(f'{path.name} changed while being read. Please retry.')
                    if _digest(data) != hashes[path.name]:
                        raise ArchiveError(f'{path.name} differs from the archived workflow. No files were removed. Keep both versions by renaming one with its accompanying media first.')
                originals[path] = source_stamp
                sources[path.name] = source_stamp
                result.reused += 1
                continue
            data = _workflow_bytes(path)
            if data is None:
                if path.exists():
                    result.skipped += 1
                continue
            if _source_stamp(path) != source_stamp:
                raise ArchiveError(f'{path.name} changed while being read. Please retry.')
            digest = _digest(data)
            (inputs / path.name).write_bytes(data)
            hashes[path.name] = digest
            sizes[path.name] = len(data)
            sources[path.name] = source_stamp
            names_by_case[path.name.casefold()] = path.name
            originals[path] = source_stamp
            additions.append(path.name)
        reporter.update(
            f'Checked {total:,} / {total:,} accompanying JSON candidates; '
            f'{len(originals):,} workflows found; {result.skipped:,} other JSON skipped.',
            total, total, force=True)
        if not hashes:
            return result
        result.source_bytes = sum(sizes.values())
        if result.source_bytes > MAX_TOTAL_BYTES:
            raise ArchiveError('Workflows exceed the 4 GiB unpacked safety limit.')
        if additions:
            output = staging / ARCHIVE_NAME
            if original_stamp:
                # Updating a working copy preserves the last good archive if
                # compression is cancelled. Only compressed bytes are copied.
                _copy_archive(archive, output, cancel, reporter)
            _run(['a', '-t7z', '-m0=lzma2', '-mx=7', '-ms=64m', '-mmt=2', '-sse', str(output), '.'],
                 cwd=inputs, cancel=cancel, progress=progress,
                 phase=f'Compressing {len(additions):,} new workflows')
            # Store the index in its own block. Future index updates do not
            # force recompression of the workflow blocks beside it.
            (inputs / MANIFEST_NAME).write_text(json.dumps({
                'format': 'taggui-workflows-1', 'sha256': hashes, 'sources': sources}), encoding='utf-8')
            _run(['a', '-t7z', '-ms=off', '-mmt=2', str(output), MANIFEST_NAME],
                 cwd=inputs, cancel=cancel, progress=progress, phase='Updating archive index')
            selected = staging / 'verify.txt'
            selected.write_text('\n'.join([*additions, MANIFEST_NAME]), encoding='utf-8')
            _run(['t', '-t7z', '-spd', '-scsUTF-8', f'-i@{selected}', str(output)],
                 cancel=cancel, progress=progress, phase='Verifying newly archived files')
            check_cancel(cancel)
            if archive_stamp(archive) != original_stamp:
                raise ArchiveError('Archive changed while compressing. Original files were kept.')
            with output.open('rb+') as stream:
                os.fsync(stream.fileno())
            os.replace(output, archive)
            if os.name != 'nt':
                directory_fd = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            result.archive_updated = True
            result.added = len(additions)
        else:
            progress('No new workflows. Reusing the existing archive without recompressing.')
            if archive_stamp(archive) != original_stamp:
                raise ArchiveError('Archive changed during the scan. Please retry.')
        published_stamp = archive_stamp(archive)
        result.archive_bytes = published_stamp[0]
        result.archived = len(hashes)
        if remove_originals:
            progress('Removing only unchanged, verified originals…')
            recovery = Path(tempfile.mkdtemp(prefix='.workflow-originals-', dir=folder))
            try:
                for checked, (path, source_stamp) in enumerate(originals.items()):
                    check_cancel(cancel)
                    reporter.update(
                        f'Cleaning up verified originals: {checked:,} / {len(originals):,}; '
                        f'{result.removed:,} removed; {len(result.retained):,} kept.\nCurrent: {path.name}',
                        checked, len(originals))
                    if archive_stamp(archive) != published_stamp:
                        raise ArchiveError('Archive changed during cleanup. No further originals were removed.')
                    try:
                        retained = _remove_original(path, archive, published_stamp, recovery, source_stamp)
                        if retained is None:
                            result.removed += 1
                        else:
                            result.retained.append(retained)
                    except OSError:
                        result.retained.append(path.name)
            finally:
                try:
                    recovery.rmdir()  # Only empty recovery directories are removed.
                except OSError:
                    pass
    return result


def restore_archive(folder, *, cancel=None, progress=lambda text: None):
    folder = Path(folder).resolve()
    result = ArchiveResult()
    with _folder_lock(folder), tempfile.TemporaryDirectory(prefix='.workflow-restore-', dir=folder) as temporary:
        staging = Path(temporary)
        progress('Extracting and verifying archived workflows…')
        hashes = _unpack(folder / ARCHIVE_NAME, staging, cancel)
        for name, digest in hashes.items():
            check_cancel(cancel)
            destination = folder / name
            try:
                # Same-volume hard link publishes a complete file atomically,
                # and fails if a file (including a symlink) already exists.
                _publish_without_replace(staging / name, destination)
                result.restored += 1
            except FileExistsError:
                if (destination.is_file() and not destination.is_symlink()
                        and _digest(destination.read_bytes()) == digest):
                    result.unchanged += 1
                else:
                    result.retained.append(name)
    return result


class WorkflowDragCache:
    """Session cache. Only prepare() does decompression, on a worker thread."""
    def __init__(self):
        self._temporary = None
        self._entries = {}
        self._lock = threading.Lock()

    def key(self, media):
        archive = Path(media).parent / ARCHIVE_NAME
        return (str(archive.resolve()), archive_stamp(archive), Path(media).with_suffix('.json').name)

    def lookup(self, media):
        key = self.key(media)
        if key[1] is None:
            return True, None
        with self._lock:
            if key not in self._entries:
                return False, None
            path = self._entries[key]
        return (True, path) if path is None or path.is_file() else (False, None)

    def prepare(self, paths, *, cancel=None, progress=lambda text: None):
        for media in paths:
            check_cancel(cancel)
            if self.lookup(media)[0]:
                continue
            key = self.key(media)
            archive = Path(key[0])
            progress(f'Preparing {key[2]} from workflows.7z…')
            members = _members(archive, cancel)
            path = None
            if key[2] in members:
                # stdout avoids archive-controlled filesystem paths and only
                # decodes the solid block needed for this particular member.
                with tempfile.TemporaryFile() as stream:
                    _run(['x', '-so', '-spd', '-t7z', str(archive), '--', key[2]], cancel=cancel,
                         output_file=stream, output_limit=members[key[2]])
                    stream.seek(0)
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) != members[key[2]] or not is_workflow(json.loads(data)):
                    raise ArchiveError(f'Invalid archived workflow: {key[2]}')
                with self._lock:
                    if self._temporary is None:
                        self._temporary = tempfile.TemporaryDirectory(prefix='taggui-workflow-drag-')
                    directory = Path(self._temporary.name) / hashlib.sha256(repr(key).encode()).hexdigest()
                    directory.mkdir(exist_ok=True)
                    path = directory / key[2]
                    path.write_bytes(data)
            if self.key(media) != key:
                raise ArchiveError('Archive changed while preparing the drag. Please retry.')
            with self._lock:
                self._entries[key] = path


drag_cache = WorkflowDragCache()
