#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from utils.instance_relay import preferred_server_name, send_open_request


def _resolve_target(raw_target: str) -> tuple[Path | None, str | None]:
    if not raw_target:
        return None, None
    candidate = Path(raw_target).expanduser()
    try:
        candidate = candidate.resolve()
    except Exception:
        candidate = candidate.absolute()

    if candidate.is_dir():
        return candidate, None
    if candidate.is_file():
        return candidate.parent, str(candidate)
    return None, None


def _launch_new_instance(directory_path: Path, select_path: str | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if sys.platform.startswith('win'):
        launcher = repo_root / 'start_windows.bat'
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        launcher = repo_root / 'start_linux.sh'
        creation_flags = 0
    if not launcher.is_file():
        return 1

    target_arg = str(select_path or directory_path)
    try:
        subprocess.Popen(
            [str(launcher), target_arg],
            cwd=str(repo_root),
            creationflags=creation_flags,
        )
    except Exception:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Send a folder-open request to a running TagGUI window.')
    parser.add_argument('target', nargs='?')
    parser.add_argument('--open', dest='open_target')
    args = parser.parse_args(list(argv or []))

    raw_target = args.open_target or args.target
    directory_path, select_path = _resolve_target(str(raw_target or '').strip())
    if directory_path is None:
        return 2

    app = QCoreApplication([])
    _ = app
    server_name = preferred_server_name()
    if server_name and send_open_request(
        server_name=server_name,
        directory_path=directory_path,
        select_path=select_path,
        timeout_ms=700,
    ):
        return 0
    return _launch_new_instance(directory_path, select_path=select_path)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
