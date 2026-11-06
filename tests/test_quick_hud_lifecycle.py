"""Deferred HUD positioning must not outlive its viewport."""

import sys

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget

from controllers.quick_tag_controller import QuickTagHud
from qt_test_helpers import APP, dispose_widget


def test_queued_hud_reposition_does_not_outlive_destroyed_viewport(monkeypatch):
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))
    first, sibling = QWidget(), QWidget()
    first.resize(300, 200)
    sibling.resize(300, 200)
    first_hud, sibling_hud = QuickTagHud(first), QuickTagHud(sibling)
    try:
        first.show()
        sibling.show()
        APP.processEvents()
        # Both deferred paths must be discarded with the first HUD.
        first_hud.eventFilter(first, QEvent(QEvent.Type.Resize))
        first_hud.set_pending(['pending'], [])
        dispose_widget(first)
        APP.processEvents()
        sibling_hud.set_pending(['still usable'], [])
        APP.processEvents()
        assert sibling_hud._pending_tags == ['still usable']
        assert not errors
    finally:
        dispose_widget(sibling)
        APP.processEvents()
