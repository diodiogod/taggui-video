from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_folder_restore_does_not_use_legacy_targeted_relocation():
    main_window_source = (ROOT / "taggui" / "widgets" / "main_window.py").read_text(
        encoding="utf-8"
    )

    assert "reason='async_refresh_restore'" not in main_window_source
    assert "def _try_apply_safe_recenter" in main_window_source
    assert "get_loaded_row_for_global_index" in main_window_source
    assert "SelectionFlag.ClearAndSelect" in main_window_source


def test_relocation_boundary_explicitly_rejects_async_restore():
    interaction_source = (
        ROOT / "taggui" / "widgets" / "image_list_view_interaction_mixin.py"
    ).read_text(encoding="utf-8")

    guard = 'if async_restore:\n            # Disabled after repeated native Qt crashes'
    assert guard in interaction_source
    assert "return False" in interaction_source[interaction_source.index(guard):]
