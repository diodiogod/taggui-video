import os
from pathlib import Path


def test_auxiliary_library_settings_remain_in_the_isolated_test_root():
    """A dependency import must not fall back to user or repository settings."""
    from ultralytics.utils import SETTINGS
    from utils.settings import settings
    root = Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve().parent
    actual = Path(SETTINGS.file).resolve()
    assert actual.is_relative_to(root)
    assert actual.is_relative_to(Path(os.environ['YOLO_CONFIG_DIR']).resolve())
    assert Path(settings.fileName()).resolve().is_relative_to(root)
    assert actual.is_file()
