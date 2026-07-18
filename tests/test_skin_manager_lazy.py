from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from skins.engine import SkinManager


def test_lazy_skin_manager_loads_selected_skin_before_full_catalog(monkeypatch):
    manager = SkinManager(discover_on_init=False)

    assert manager.available_skins == []
    assert manager.load_skin("Classic")
    assert manager.get_current_skin_name() == "Classic"
    assert len(manager.available_skins) == 1

    manager.refresh_available_skins()
    assert len(manager.available_skins) > 1
    assert any(skin["name"] == "Classic" for skin in manager.available_skins)

    def unexpected_reload(_skin_dirs):
        raise AssertionError("unchanged skin catalog should not be reparsed")

    monkeypatch.setattr(manager.loader, "list_available_skins", unexpected_reload)
    manager.refresh_available_skins()
