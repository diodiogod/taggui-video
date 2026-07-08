from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from utils.marking_model_security import infer_marking_model_task


def _find_exported_onnx_path(work_dir: Path) -> Path | None:
    candidates = sorted(
        work_dir.rglob("*.onnx"),
        key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _copy_with_windows_retry(source_path: Path, output_path: Path):
    source_resolved = source_path.resolve()
    output_resolved = output_path.resolve()
    if source_resolved == output_resolved:
        return

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    last_error = None
    for attempt in range(8):
        try:
            if temp_output.exists():
                temp_output.unlink()
            shutil.copy2(source_path, temp_output)
            os.replace(temp_output, output_path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
        finally:
            try:
                if temp_output.exists() and not output_path.exists():
                    temp_output.unlink()
            except Exception:
                pass
    if last_error is not None:
        raise last_error


def _to_filetime(unix_seconds: float):
    intervals = int(unix_seconds * 10_000_000) + 116_444_736_000_000_000
    return ctypes.c_ulong(intervals & 0xFFFFFFFF), ctypes.c_ulong(intervals >> 32)


def _set_windows_creation_time(path: Path, source_stat):
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    GENERIC_WRITE = 0x40000000
    FILE_WRITE_ATTRIBUTES = 0x0100
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    handle = kernel32.CreateFileW(
        str(path),
        GENERIC_WRITE | FILE_WRITE_ATTRIBUTES,
        0,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        return
    try:
        created_low, created_high = _to_filetime(source_stat.st_ctime)
        accessed_low, accessed_high = _to_filetime(source_stat.st_atime)
        modified_low, modified_high = _to_filetime(source_stat.st_mtime)
        created = ctypes.wintypes.FILETIME(created_low.value, created_high.value)
        accessed = ctypes.wintypes.FILETIME(accessed_low.value, accessed_high.value)
        modified = ctypes.wintypes.FILETIME(modified_low.value, modified_high.value)
        kernel32.SetFileTime(
            handle,
            ctypes.byref(created),
            ctypes.byref(accessed),
            ctypes.byref(modified),
        )
    finally:
        kernel32.CloseHandle(handle)


def _apply_source_timestamps(source_path: Path, output_path: Path):
    source_stat = source_path.stat()
    os.utime(
        output_path,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
    )
    _set_windows_creation_time(output_path, source_stat)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    args = parser.parse_args(list(argv or []))

    input_path = Path(args.input_path).expanduser().resolve()
    output_path = Path(args.output_path).expanduser().resolve()

    if not input_path.is_file():
        print(f"Input model not found: {input_path}", file=sys.stderr)
        return 2

    from ultralytics import YOLO

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="taggui_marking_import_") as temp_dir:
        work_dir = Path(temp_dir)
        model = YOLO(
            str(input_path),
            task=infer_marking_model_task(input_path),
        )
        exported_path = model.export(
            format="onnx",
            project=str(work_dir),
            name="export",
            exist_ok=True,
        )

        candidate = Path(str(exported_path)).expanduser()
        if not candidate.is_file():
            candidate = _find_exported_onnx_path(work_dir) or candidate
        if not candidate.is_file():
            print("Ultralytics export did not produce an ONNX file.", file=sys.stderr)
            return 3

        _copy_with_windows_retry(candidate, output_path)
        _apply_source_timestamps(input_path, output_path)

    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
