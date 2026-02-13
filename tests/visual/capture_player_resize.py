#!/usr/bin/env python3
"""Capture runtime-like player screenshots across resize widths.

Usage examples:
  python tests/visual/capture_player_resize.py --offscreen
  python tests/visual/capture_player_resize.py --widths 1200 1000 800 600 480 --outdir /tmp/taggui-capture
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Capture player screenshots across widths")
    p.add_argument(
        "--widths",
        nargs="+",
        type=int,
        default=[1200, 1000, 850, 700, 560, 460],
        help="Player widths to capture (px)",
    )
    p.add_argument("--height", type=int, default=180, help="Initial player height (px)")
    p.add_argument("--offscreen", action="store_true", help="Use Qt offscreen platform")
    p.add_argument(
        "--mode",
        choices=["image_viewer", "overlay"],
        default="image_viewer",
        help="Capture path: full ImageViewer overlay path (default) or raw overlay host.",
    )
    p.add_argument(
        "--outdir",
        type=str,
        default="",
        help="Output directory (default: temp dir with timestamp)",
    )
    p.add_argument("--skin", type=str, default="", help="Optional skin name to load")
    return p.parse_args()


def ensure_import_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "taggui"))
    return repo_root


def main() -> int:
    args = parse_args()

    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    repo_root = ensure_import_paths()

    from PySide6.QtCore import QTimer, QObject, Signal, QModelIndex, Qt
    from PySide6.QtGui import QColor, QBrush
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
    from taggui.widgets.video_controls import VideoControlsWidget
    from taggui.widgets.image_viewer import ImageViewer

    app = QApplication(sys.argv)

    if args.outdir:
        outdir = Path(args.outdir)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = Path(tempfile.gettempdir()) / f"taggui_player_resize_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    win = QMainWindow()
    win.setWindowTitle("TagGUI Player Resize Capture")

    class _DummyProxyModel(QObject):
        modelAboutToBeReset = Signal()
        modelReset = Signal()

        def sourceModel(self):
            return self

        def mapToSource(self, _index):
            return QModelIndex()

        def rowCount(self):
            return 0

        def data(self, _index, _role=None):
            return None

    if args.mode == "image_viewer":
        viewer = ImageViewer(_DummyProxyModel())
        viewer.setObjectName("captureRoot")
        viewer.setStyleSheet("#captureRoot { background-color: #121212; }")
        # Match runtime dark media area instead of default light GraphicsView background.
        viewer.scene.setBackgroundBrush(QBrush(QColor("#121212")))
        viewer.view.setBackgroundBrush(QBrush(QColor("#121212")))
        viewer.view.setFrameStyle(0)
        viewer.view.viewport().setAutoFillBackground(False)
        viewer.view.setStyleSheet("background: #121212; border: 0;")
        viewer.video_controls_auto_hide = False
        viewer._is_video_loaded = True
        viewer.video_controls.setVisible(True)
        viewer.video_controls.raise_()
        win.setCentralWidget(viewer)
        central = viewer
        controls = viewer.video_controls
    else:
        central = QWidget(win)
        central.setObjectName("captureRoot")
        win.setCentralWidget(central)
        central.setStyleSheet("#captureRoot { background-color: #121212; }")
        controls = VideoControlsWidget(central)
        controls.setVisible(True)
        controls.setMinimumHeight(100)
        controls.setMinimumWidth(120)
        controls.setMaximumWidth(16777215)
        controls.resize(max(args.widths), max(100, args.height))

    if args.skin:
        controls.skin_manager.load_skin(args.skin)
    controls.apply_current_skin()

    # Make timeline + markers visible for visual comparison.
    controls.frame_spinbox.setMaximum(100)
    controls.timeline_slider.setMinimum(0)
    controls.timeline_slider.setMaximum(100)
    controls.timeline_slider.setValue(40)
    controls.apply_loop_state(18, 78, False, save=False, emit_signals=False)

    window_w = max(args.widths) + 120
    window_h = 380
    win.resize(window_w, window_h)
    win.show()

    captures: list[tuple[int, Path, Path]] = []

    def place_controls(width: int) -> None:
        """Place controls like runtime overlay: bottom-centered, explicit geometry."""
        controls_height = controls.sizeHint().height()
        width_clamped = max(400, min(int(width), max(400, int(central.width()))))
        x_pos = (central.width() - width_clamped) // 2
        y_pos = max(0, central.height() - controls_height)
        controls.setGeometry(int(x_pos), int(y_pos), int(width_clamped), int(controls_height))
        controls.raise_()

    def capture_at_index(i: int = 0) -> None:
        if i >= len(args.widths):
            manifest = outdir / "manifest.txt"
            lines = [
                f"repo={repo_root}",
                f"offscreen={args.offscreen}",
                f"mode={args.mode}",
                f"skin={args.skin or 'current-default'}",
                "",
                "captures:",
            ]
            for w, player_path, window_path in captures:
                lines.append(f"  width={w} player={player_path.name} window={window_path.name}")
            manifest.write_text("\n".join(lines), encoding="utf-8")
            print(f"Saved {len(captures)} capture sets to: {outdir}")
            app.quit()
            return

        width = int(args.widths[i])
        place_controls(width)
        app.processEvents()

        # Allow async relayout/skin scaling to settle.
        QTimer.singleShot(120, lambda: do_capture(width, i))

    def do_capture(width: int, idx: int) -> None:
        app.processEvents()
        player_img = controls.grab().toImage()
        window_img = win.grab().toImage()

        player_path = outdir / f"player_w{width:04d}.png"
        window_path = outdir / f"window_w{width:04d}.png"

        player_img.save(str(player_path))
        window_img.save(str(window_path))
        captures.append((width, player_path, window_path))

        capture_at_index(idx + 1)

    QTimer.singleShot(120, capture_at_index)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
