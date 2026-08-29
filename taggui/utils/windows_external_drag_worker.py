"""Disposable Qt process which owns one Windows shell file drag."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def main() -> int:
    manifest_path = Path(sys.argv[1])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    urls = [QUrl.fromLocalFile(path) for path in payload.get("paths", []) if path]
    if not urls:
        return 2

    app = QApplication.instance() or QApplication([sys.argv[0]])
    source = QWidget()
    mime_data = QMimeData()
    mime_data.setUrls(urls)
    drag = QDrag(source)
    drag.setMimeData(mime_data)

    preview = QPixmap(str(manifest_path.with_name("preview.png")))
    if not preview.isNull():
        drag.setPixmap(preview)
        drag.setHotSpot(preview.rect().center())

    drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
