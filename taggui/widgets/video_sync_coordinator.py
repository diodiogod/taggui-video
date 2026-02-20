"""
Event-driven multi-window video sync coordinator.

Design:
  1. Disable per-player looping. Each player emits playback_finished when done.
  2. Coordinator counts finished players.
  3. When ALL have finished → barrier (pause+seek+settle) → restart all together.
  4. Repeat indefinitely while coordinator is active.

Fallback: if any player stalls and never emits playback_finished, a watchdog
timer fires after (longest_duration + STALL_TIMEOUT_MS) and forces a restart.

Sync icon: small "⟳ SYNC" label on each viewer while active.
"""

import time
from PySide6.QtCore import QObject, QTimer, Qt, Slot
from PySide6.QtWidgets import QLabel

# Poll interval used only during the barrier phase.
_POLL_INTERVAL_MS = 16

# Minimum settle time after issuing pause before barrier can pass.
_MIN_SETTLE_MS = 100.0

# Hard timeout on the barrier itself.
_MAX_BARRIER_MS = 800

# Extra ms added to longest duration for the stall watchdog.
_STALL_TIMEOUT_MS = 1500

_SYNC_ICON_STYLE = """
    QLabel {
        background: rgba(0, 0, 0, 140);
        color: rgba(255, 255, 255, 220);
        border: 1px solid rgba(255, 255, 255, 60);
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 11px;
        font-weight: bold;
    }
"""


class _PlayerEntry:
    def __init__(self, viewer):
        self.viewer = viewer
        self.player = viewer.video_player
        self.start_ms = 0.0
        self.end_ms = 0.0
        self.duration_ms = 0.0
        self.finished = False
        self._sync_label: QLabel | None = None

    def resolve_bounds(self):
        player = self.player
        self.duration_ms = max(0.0, float(player.duration_ms or 0.0))
        try:
            controls = self.viewer.video_controls
            if bool(getattr(controls, 'is_looping', False)):
                loop_range = controls.get_loop_range()
                if loop_range:
                    fps = max(1.0, float(player.fps or 25.0))
                    self.start_ms = (max(0, int(loop_range[0])) / fps) * 1000.0
                    self.end_ms = (max(0, int(loop_range[1])) / fps) * 1000.0
                    return
        except Exception:
            pass
        self.start_ms = 0.0
        self.end_ms = self.duration_ms

    def ensure_vlc_ready(self):
        """Pre-warm VLC so fire_play() has no setup overhead."""
        player = self.player
        if player.vlc_player is None or player._vlc_needs_reload:
            player.is_playing = False
            try:
                player.play()
            except Exception:
                pass
            try:
                player.pause()
            except Exception:
                pass

    def disable_loop(self):
        """Turn off per-player looping so playback_finished is emitted at end."""
        try:
            self.player.set_loop(False, None, None)
        except Exception:
            pass

    def pause_hard(self):
        player = self.player
        try:
            player.pause()
        except Exception:
            pass
        if player.vlc_player is not None:
            try:
                player._set_vlc_paused(True)
            except Exception:
                pass

    def seek_to_start(self):
        player = self.player
        try:
            if player.fps > 0:
                player.seek_to_frame(int(self.start_ms / 1000.0 * player.fps))
        except Exception:
            pass
        if player.vlc_player is not None:
            try:
                from utils.video.playback_backend import VLC_PYTHON_MODULE
                vlc = VLC_PYTHON_MODULE
                # If VLC is in Ended/Stopped state, stop() resets the state machine
                # so that the next play() actually starts from the beginning.
                if vlc is not None:
                    state = player.vlc_player.get_state()
                    terminal = {
                        getattr(vlc.State, s, None)
                        for s in ("Ended", "Stopped", "Error", "NothingSpecial")
                    }
                    terminal.discard(None)
                    if state in terminal:
                        player.vlc_player.stop()
            except Exception:
                pass
            try:
                player.vlc_player.set_time(int(max(0.0, self.start_ms)))
            except Exception:
                pass
            try:
                player._vlc_estimated_position_ms = float(self.start_ms)
                player._vlc_end_reached_flag = False
                player._vlc_last_progress_ms = float(self.start_ms)
                player._vlc_stall_ticks = 0
            except Exception:
                pass

    def fire_play(self):
        self.finished = False
        player = self.player
        player.is_playing = False
        try:
            player.play()
        except Exception:
            pass

    def is_ready(self) -> bool:
        """True when the player is fully paused (not Playing/Buffering in VLC)."""
        player = self.player
        if bool(getattr(player, 'is_playing', False)):
            return False
        if player.vlc_player is not None:
            try:
                from utils.video.playback_backend import VLC_PYTHON_MODULE
                vlc = VLC_PYTHON_MODULE
                if vlc is not None:
                    state = player.vlc_player.get_state()
                    active = {
                        getattr(vlc.State, s, None)
                        for s in ("Playing", "Buffering", "Opening")
                    }
                    active.discard(None)
                    if state in active:
                        return False
            except Exception:
                pass
        return True

    def show_sync_icon(self):
        try:
            if self._sync_label is not None:
                return
            label = QLabel("⟳ SYNC", self.viewer)
            label.setStyleSheet(_SYNC_ICON_STYLE)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.adjustSize()
            label.move(8, 8)
            label.show()
            label.raise_()
            self._sync_label = label
        except Exception:
            pass

    def hide_sync_icon(self):
        try:
            if self._sync_label is not None:
                self._sync_label.deleteLater()
                self._sync_label = None
        except Exception:
            pass


class VideoSyncCoordinator(QObject):
    """
    Event-driven coordinator: waits for all players to finish, then restarts all.
    """

    _STATE_IDLE = "idle"
    _STATE_WARMING = "warming"
    _STATE_BARRIER = "barrier"
    _STATE_RUNNING = "running"

    def __init__(self, viewers: list, parent=None, *, show_sync_icon: bool = True):
        super().__init__(parent)
        self._show_sync_icon = bool(show_sync_icon)
        self._entries: list[_PlayerEntry] = []
        for v in viewers:
            try:
                player = getattr(v, 'video_player', None)
                if player is not None and getattr(player, 'video_path', None):
                    self._entries.append(_PlayerEntry(v))
            except Exception:
                pass

        self._state = self._STATE_IDLE
        self._barrier_start_monotonic = 0.0
        self._pause_issued_monotonic = 0.0
        self._play_started_monotonic = 0.0
        self._longest_duration_ms = 0.0
        self._finished_count = 0

        # Barrier poll timer — only active during barrier phase.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_barrier)

        # Stall watchdog — fires if players never emit playback_finished.
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.timeout.connect(self._on_watchdog)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if not self._entries:
            return
        for entry in self._entries:
            try:
                entry.resolve_bounds()
            except Exception:
                pass

        self._longest_duration_ms = max(
            (e.end_ms for e in self._entries), default=0.0
        )

        for entry in self._entries:
            if self._show_sync_icon:
                entry.show_sync_icon()
            entry.disable_loop()
            # Connect playback_finished signal.
            try:
                entry.player.playback_finished.connect(
                    self._on_player_finished, Qt.ConnectionType.QueuedConnection
                )
            except Exception:
                pass

        # Pre-warm VLC before the barrier.
        for entry in self._entries:
            entry.ensure_vlc_ready()

        self._state = self._STATE_WARMING
        QTimer.singleShot(250, self._on_warming_done)

    def stop(self):
        self._poll_timer.stop()
        self._watchdog_timer.stop()
        self._state = self._STATE_IDLE
        for entry in self._entries:
            try:
                entry.player.playback_finished.disconnect(self._on_player_finished)
            except Exception:
                pass
            entry.hide_sync_icon()

    # ------------------------------------------------------------------
    # Warming
    # ------------------------------------------------------------------

    def _on_warming_done(self):
        if self._state != self._STATE_WARMING:
            return
        self._state = self._STATE_BARRIER
        self._begin_barrier()

    # ------------------------------------------------------------------
    # Barrier
    # ------------------------------------------------------------------

    def _begin_barrier(self):
        if self._state == self._STATE_IDLE:
            return
        self._finished_count = 0
        for entry in self._entries:
            entry.finished = False
        for entry in self._entries:
            entry.pause_hard()
        for entry in self._entries:
            entry.seek_to_start()
        now = time.monotonic()
        self._pause_issued_monotonic = now
        self._barrier_start_monotonic = now
        QTimer.singleShot(60, self._reseek_all)
        self._poll_timer.start()

    def _reseek_all(self):
        if self._state != self._STATE_BARRIER:
            return
        for entry in self._entries:
            entry.seek_to_start()
            entry.pause_hard()

    @Slot()
    def _poll_barrier(self):
        timed_out = (time.monotonic() - self._barrier_start_monotonic) * 1000.0 >= _MAX_BARRIER_MS
        settled = (time.monotonic() - self._pause_issued_monotonic) * 1000.0 >= _MIN_SETTLE_MS
        all_ready = all(e.is_ready() for e in self._entries)

        if (settled and all_ready) or timed_out:
            elapsed = (time.monotonic() - self._barrier_start_monotonic) * 1000.0
            if timed_out and not (settled and all_ready):
                print(f"[SYNC] Barrier timed out after {elapsed:.0f}ms — firing anyway")
            else:
                print(f"[SYNC] Barrier passed after {elapsed:.0f}ms")
            self._poll_timer.stop()
            self._fire_play_all()

    # ------------------------------------------------------------------
    # Running — wait for all players to finish
    # ------------------------------------------------------------------

    @Slot()
    def _on_player_finished(self):
        sender = self.sender()
        idx = next((i for i, e in enumerate(self._entries) if e.player is sender), -1)
        already = self._entries[idx].finished if idx >= 0 else "?"
        print(f"[SYNC] playback_finished player={idx} already_finished={already} state={self._state} count={self._finished_count+1}/{len(self._entries)}")
        if self._state != self._STATE_RUNNING:
            return
        if idx >= 0 and self._entries[idx].finished:
            print(f"[SYNC] duplicate finished from player={idx} — ignoring")
            return
        self._finished_count += 1
        if idx >= 0:
            self._entries[idx].finished = True

        if self._finished_count >= len(self._entries):
            print(f"[SYNC] all finished — beginning barrier")
            self._watchdog_timer.stop()
            self._state = self._STATE_BARRIER
            self._begin_barrier()

    @Slot()
    def _on_watchdog(self):
        """Force restart if one or more players stalled and never finished."""
        if self._state != self._STATE_RUNNING:
            return
        stalled = [e for e in self._entries if not e.finished]
        if stalled:
            print(f"[SYNC] Watchdog: {len(stalled)} player(s) stalled — forcing restart")
        self._state = self._STATE_BARRIER
        self._begin_barrier()

    # ------------------------------------------------------------------
    # Batch play
    # ------------------------------------------------------------------

    def _fire_play_all(self):
        self._state = self._STATE_RUNNING
        self._finished_count = 0
        for entry in self._entries:
            entry.finished = False
        self._play_started_monotonic = time.monotonic()
        print(f"[SYNC] firing play on {len(self._entries)} players")
        for entry in self._entries:
            entry.fire_play()
        watchdog_ms = int(self._longest_duration_ms + _STALL_TIMEOUT_MS)
        if watchdog_ms > 0:
            self._watchdog_timer.start(watchdog_ms)
        print(f"[SYNC] watchdog set for {watchdog_ms}ms")
