"""Run TagGUI tests with settings, caches and home directories isolated first.

Usage: venv/Scripts/python.exe tests/run_isolated.py [pytest arguments]
"""
import os
from pathlib import Path
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="taggui-tests-") as directory:
        root = Path(directory).resolve()
        for variable, name in (
            ("APPDATA", "config"), ("LOCALAPPDATA", "local"),
            ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "state"),
            ("USERPROFILE", "home"), ("HOME", "home"),
            ("YOLO_CONFIG_DIR", "yolo"),
        ):
            path = root / name
            path.mkdir(exist_ok=True)
            os.environ[variable] = str(path)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ['TAGGUI_SETTINGS_PATH'] = str(root / 'settings.ini')
        from PySide6.QtCore import QSettings, QStandardPaths
        QSettings.setDefaultFormat(QSettings.IniFormat)
        for scope in (QSettings.UserScope, QSettings.SystemScope):
            QSettings.setPath(QSettings.IniFormat, scope, str(root / "settings"))
        QStandardPaths.setTestModeEnabled(True)
        repository = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(repository), str(repository / "taggui")]
        # Both import spellings occur in existing tests. Configure before any
        # application services can instantiate the thumbnail cache singleton.
        from utils.settings import settings
        from taggui.utils.settings import settings as package_settings
        # Verify both actual stores before the first mutation. Windows ignores
        # setDefaultFormat for the org/application QSettings overload.
        for store in (settings, package_settings):
            assert Path(store.fileName()).resolve().is_relative_to(root)
        for store in (settings, package_settings):
            store.setValue("thumbnail_cache_location", str(root / "thumbnails"))
            store.setValue("_last_thumbnail_cache_location", str(root / "thumbnails"))
            store.setValue("_thumbnail_cache_png_cleanup_v1", True)
            store.setValue("_thumbnail_cache_purge_v1", True)
            store.setValue("repair_extensionless_images", False)
            store.sync()
            assert Path(store.value('thumbnail_cache_location')).resolve().is_relative_to(root)
            assert Path(store.value('_last_thumbnail_cache_location')).resolve().is_relative_to(root)
        print(f"Isolated test settings/cache/home: {root}")
        import pytest
        return pytest.main(sys.argv[1:] or ["tests", "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
