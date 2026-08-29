"""Crash containment for Windows shell file drags."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_isolated_external_drag(paths, pixmap) -> int:
    """Run the native OLE drag in a disposable helper process.

    Qt's Windows drag implementation can fail with an uncatchable native access
    violation.  Keeping that OLE loop out of the GUI process prevents such a
    driver/Qt failure from terminating TagGUI.
    """
    worker = Path(__file__).with_name("windows_external_drag_worker.py")
    with tempfile.TemporaryDirectory(prefix="taggui-drag-") as temp_dir:
        temp_path = Path(temp_dir)
        manifest_path = temp_path / "drag.json"
        preview_path = temp_path / "preview.png"
        manifest_path.write_text(
            json.dumps({"paths": [str(path) for path in paths]}),
            encoding="utf-8",
        )
        if pixmap is not None and not pixmap.isNull():
            pixmap.save(str(preview_path), "PNG")

        command = [sys.executable, str(worker), str(manifest_path)]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            check=False,
        )
        return int(completed.returncode)
