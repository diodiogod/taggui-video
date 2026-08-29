"""Lifecycle guard for Qt's nested native drag loop on Windows."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent


class QtDragSessionService:
    """Keep model/view work stable while ``QDrag.exec()`` processes events."""

    def __init__(self, view):
        self._view = view

    def _source_model(self):
        model = self._view.model()
        if model is not None and hasattr(model, "sourceModel"):
            return model.sourceModel()
        return model

    def _suspend_video_rendering(self):
        """Quiesce MPV/OpenGL surfaces before entering Windows' drag loop."""
        try:
            window = self._view.window()
        except (AttributeError, RuntimeError):
            return []
        iterator = getattr(window, "_iter_all_viewers", None)
        if not callable(iterator):
            return []

        suspended_players = []
        for viewer in iterator():
            try:
                player = getattr(viewer, "video_player", None)
                setter = getattr(player, "set_application_render_active", None)
                if player is None or not callable(setter):
                    continue
                setter(False)
                suspended_players.append(player)
            except (RuntimeError, AttributeError):
                continue
        return suspended_players

    def begin(self):
        """Start one guarded drag session, returning restoration state."""
        if bool(getattr(self._view, "_qt_drag_active", False)):
            return None

        source_model = self._source_model()
        enrichment_timer = getattr(source_model, "_enrichment_timer", None)
        timer_was_active = False
        timer_interval_ms = -1
        if enrichment_timer is not None:
            try:
                timer_was_active = bool(enrichment_timer.isActive())
                timer_interval_ms = int(enrichment_timer.interval())
            except Exception:
                timer_was_active = False
                timer_interval_ms = -1

        state = {
            "source_model": source_model,
            "pause_thumbnail_loading": getattr(source_model, "_pause_thumbnail_loading", None),
            "model_drag_active": getattr(source_model, "_native_qt_drag_active", None),
            "enrichment_timer": enrichment_timer,
            "timer_was_active": timer_was_active,
            "timer_interval_ms": timer_interval_ms,
            # A thumbnail mouse press stops enrichment and normally restarts it
            # from mouseReleaseEvent. Windows' native drag loop consumes that
            # release, so the guarded exit must perform the equivalent restart.
            "resume_pointer_enrichment": bool(
                getattr(self._view, "_suppress_selection_commit_until_release", False)
            ),
            "suspended_video_players": self._suspend_video_rendering(),
        }

        self._view._qt_drag_active = True
        if source_model is not None:
            source_model._native_qt_drag_active = True
        if source_model is not None and hasattr(source_model, "_pause_thumbnail_loading"):
            source_model._pause_thumbnail_loading = True
        if enrichment_timer is not None:
            try:
                enrichment_timer.stop()
            except Exception:
                pass
        return state

    def finish(self, state):
        """Restore every state changed by :meth:`begin`."""
        if state is None:
            return

        try:
            source_model = state.get("source_model")
            previous_pause = state.get("pause_thumbnail_loading")
            previous_model_drag_active = state.get("model_drag_active")
            if source_model is not None:
                source_model._native_qt_drag_active = bool(previous_model_drag_active)
            if (
                source_model is not None
                and previous_pause is not None
                and hasattr(source_model, "_pause_thumbnail_loading")
            ):
                source_model._pause_thumbnail_loading = previous_pause

            enrichment_timer = state.get("enrichment_timer")
            if enrichment_timer is not None:
                try:
                    if state.get("resume_pointer_enrichment"):
                        enrichment_timer.start(500)
                    elif state.get("timer_was_active"):
                        interval_ms = int(state.get("timer_interval_ms", -1))
                        enrichment_timer.start(max(0, interval_ms))
                except Exception:
                    pass
        finally:
            for player in state.get("suspended_video_players", ()):
                try:
                    player.set_application_render_active(True)
                except (RuntimeError, AttributeError):
                    continue
            self._view._qt_drag_active = False

    @staticmethod
    def retire_drag(drag) -> None:
        """Destroy a completed native drag before another nested loop starts.

        On Windows, leaving ``deleteLater()`` queued allows the old OLE data
        object to be destroyed from inside a later ``QDrag.exec()`` loop. Keep
        retirement outside that next native loop by delivering this object's
        deferred-delete event immediately after the completed drag returns.
        """
        if drag is None:
            return
        try:
            drag.deleteLater()
            QCoreApplication.sendPostedEvents(drag, QEvent.Type.DeferredDelete)
        except RuntimeError:
            pass
