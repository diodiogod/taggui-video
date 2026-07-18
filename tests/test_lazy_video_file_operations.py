from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from widgets.image_list_view_file_ops_mixin import _get_loaded_video_player


def test_delete_supports_viewer_without_constructed_video_player():
    main_window = SimpleNamespace(
        image_viewer=SimpleNamespace(video_player=None)
    )

    assert _get_loaded_video_player(main_window) is None


def test_delete_finds_constructed_video_player():
    player = SimpleNamespace(video_path=Path("video.mp4"))
    main_window = SimpleNamespace(
        image_viewer=SimpleNamespace(video_player=player)
    )

    assert _get_loaded_video_player(main_window) is player
