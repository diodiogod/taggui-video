import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from controllers.menu_manager import MenuManager
from models.image_list_model import ImageListModel
from utils.image import Image


class _View:
    def __init__(self, undo_timestamp=0, redo_timestamp=0):
        self._undo_timestamp = undo_timestamp
        self._redo_timestamp = redo_timestamp
        self._selection_redo_history = []
        self._selection_redo_timestamps = []
        self.calls = []

    def can_undo_selection(self):
        return self._undo_timestamp > 0

    def can_redo_selection(self):
        return self._redo_timestamp > 0

    def selection_undo_timestamp(self):
        return self._undo_timestamp

    def selection_redo_timestamp(self):
        return self._redo_timestamp

    def undo_selection(self):
        self.calls.append('undo')

    def redo_selection(self):
        self.calls.append('redo')


class _Effects:
    def __init__(self, undo_timestamp=0, redo_timestamp=0):
        self._undo_timestamp = undo_timestamp
        self._redo_timestamp = redo_timestamp
        self.calls = []

    def can_undo(self):
        return self._undo_timestamp > 0

    def can_redo(self):
        return self._redo_timestamp > 0

    def undo_timestamp(self):
        return self._undo_timestamp

    def redo_timestamp(self):
        return self._redo_timestamp

    def undo_action_name(self):
        return 'Source effect'

    def redo_action_name(self):
        return 'Source effect'

    def undo_last_effect(self, *, confirm=True):
        self.calls.append(('undo', confirm))

    def redo_last_effect(self):
        self.calls.append(('redo',))

    def clear_redo(self):
        self._redo_timestamp = 0


class _Model:
    def __init__(self, undo_timestamp=0, redo_timestamp=0):
        self.undo_stack = (
            [SimpleNamespace(action_name='Metadata', created_at_ns=undo_timestamp)]
            if undo_timestamp else []
        )
        self.redo_stack = (
            [SimpleNamespace(action_name='Metadata', created_at_ns=redo_timestamp)]
            if redo_timestamp else []
        )
        self.calls = []

    def undo(self):
        self.calls.append('undo')

    def redo(self):
        self.calls.append('redo')


def _manager(model, view, effects):
    manager = MenuManager.__new__(MenuManager)
    manager.main_window = SimpleNamespace(
        image_list_model=model,
        image_list=SimpleNamespace(list_view=view),
        _secondary_browser=None,
        marking_effects_controller=effects,
    )
    manager.update_undo_and_redo_actions = lambda: None
    return manager


def test_ctrl_z_uses_most_recent_non_video_history_provider():
    model = _Model(undo_timestamp=100)
    view = _View(undo_timestamp=200)
    effects = _Effects(undo_timestamp=300)
    manager = _manager(model, view, effects)

    manager.undo_active_context()

    assert effects.calls == [('undo', False)]
    assert view.calls == []
    assert model.calls == []


def test_ctrl_y_uses_oldest_exposed_redo_timestamp():
    model = _Model(redo_timestamp=300)
    view = _View(redo_timestamp=100)
    effects = _Effects(redo_timestamp=200)
    manager = _manager(model, view, effects)

    manager.redo_active_context()

    assert view.calls == ['redo']
    assert effects.calls == []
    assert model.calls == []


def test_geometry_history_resolves_displayed_image_outside_model_list(tmp_path):
    displayed_image = Image(tmp_path / 'displayed.png', (100, 100))
    model = SimpleNamespace(
        images=[],
        get_loaded_row_for_path=lambda _path: -1,
    )

    resolved, row = ImageListModel._resolve_history_snapshot_image(
        model,
        {'image': displayed_image, 'path': str(displayed_image.path)},
    )

    assert resolved is displayed_image
    assert row is None
