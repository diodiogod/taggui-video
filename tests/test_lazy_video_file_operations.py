from pathlib import Path
from types import SimpleNamespace
import sys
import pytest


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from widgets.image_list_view_file_ops_mixin import _release_video_players_for_paths
from widgets import main_window as main_window_module
from widgets.main_window import MainWindow


class Player:
    def __init__(self, video_path):
        self.video_path = video_path
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


def test_delete_supports_viewer_without_constructed_video_player():
    main_window = SimpleNamespace(
        image_viewer=SimpleNamespace(video_player=None)
    )

    assert not _release_video_players_for_paths(main_window, [Path('video.mp4')])


def test_delete_finds_constructed_video_player():
    player = Player(Path("video.mp4"))
    main_window = SimpleNamespace(
        image_viewer=SimpleNamespace(video_player=player)
    )

    assert _release_video_players_for_paths(main_window, [Path('video.mp4')])
    assert player.cleanup_calls == 1


def test_delete_only_releases_matching_players_once_across_viewers(tmp_path):
    target = tmp_path / 'target.mp4'
    matching = Player(target)
    unrelated = Player(tmp_path / 'other.mp4')
    viewers = [SimpleNamespace(video_player=player)
               for player in (None, matching, matching, unrelated)]
    main_window = SimpleNamespace(_iter_all_viewers=lambda: viewers)

    assert _release_video_players_for_paths(main_window, [target])
    assert matching.cleanup_calls == 1
    assert unrelated.cleanup_calls == 0


@pytest.mark.parametrize('loaded', [False, True])
def test_global_delete_handles_lazy_and_loaded_players(tmp_path, monkeypatch, loaded):
    path = tmp_path / 'video.mp4'
    player = Player(path) if loaded else None
    viewer = SimpleNamespace(video_player=player)
    image = SimpleNamespace(path=path, is_video=True, thumbnail=object(), marked_for_deletion=True)
    removed = []
    model = SimpleNamespace(remove_generated_media_batch=lambda paths: removed.extend(paths) or len(paths))
    dock = SimpleNamespace(
        collect_marked_for_deletion=lambda: ([image], [0]),
        proxy_image_list_model=SimpleNamespace(sourceModel=lambda: model),
    )
    main_window = SimpleNamespace(_iter_all_viewers=lambda: [viewer])
    trashed = []

    class FakeFile:
        def __init__(self, file_path):
            self.path = Path(file_path)

        def moveToTrash(self):
            if loaded:
                assert player.cleanup_calls == 1, 'Release native handles before trashing'
            trashed.append(self.path)
            return True

    monkeypatch.setattr(main_window_module, 'QFile', FakeFile)
    monkeypatch.setattr(main_window_module, 'QThread', SimpleNamespace(msleep=lambda _: None))
    monkeypatch.setattr(main_window_module, 'QApplication', SimpleNamespace(processEvents=lambda: None))
    monkeypatch.setattr(main_window_module, 'get_confirmation_dialog_reply',
                        lambda *_args: main_window_module.QMessageBox.StandardButton.Yes)

    MainWindow.delete_marked_images_globally(main_window, target_docks=[dock])

    assert trashed == removed == [path]
    assert not image.marked_for_deletion
    assert image.thumbnail is None
    assert viewer.video_player is player
    if loaded:
        assert player.cleanup_calls == 1
