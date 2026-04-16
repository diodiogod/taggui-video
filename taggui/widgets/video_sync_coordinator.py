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
_SYNC_DEBUG = False
_HEAVY_WARMUP_THRESHOLD = 8
_HEAVY_WARMUP_BATCH_SIZE = 2
_HEAVY_WARMUP_STEP_MS = 45
_WARMUP_SETTLE_MS = 220

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


def _sync_log(message: str):
    if _SYNC_DEBUG:
        print(message)


class _PlayerEntry:
    def __init__(self, viewer):
        self.viewer = viewer
        self.player = viewer.video_player
        self.start_frame: int | None = None
        self.end_frame: int | None = None
        self.start_ms = 0.0
        self.end_ms = 0.0
        self.duration_ms = 0.0
        self.cycle_duration_ms = 0.0
        self.finished = False
        self._sync_label: QLabel | None = None

    def resolve_bounds(self):
        player = self.player
        self.start_frame = None
        self.end_frame = None
        self.duration_ms = max(0.0, float(player.duration_ms or 0.0))
        self.cycle_duration_ms = self.duration_ms
        try:
            controls = self.viewer.video_controls
            if bool(getattr(controls, 'is_looping', False)):
                loop_range = controls.get_loop_range()
                if loop_range:
                    fps = max(1.0, float(player.fps or 25.0))
                    self.start_frame = max(0, int(loop_range[0]))
                    self.end_frame = max(0, int(loop_range[1]))
                    if self.start_frame > self.end_frame:
                        self.start_frame, self.end_frame = self.end_frame, self.start_frame
                    self.start_ms = (self.start_frame / fps) * 1000.0
                    # Match the player's inclusive loop marker behavior:
                    # loop-end is the start of the frame after loop_end.
                    self.end_ms = ((self.end_frame + 1) / fps) * 1000.0
                    self.end_ms = min(self.duration_ms, self.end_ms) if self.duration_ms > 0 else self.end_ms
                    self.cycle_duration_ms = max(1.0, self.end_ms - self.start_ms)
                    return
        except Exception:
            pass
        self.start_ms = 0.0
        self.end_ms = self.duration_ms
        self.cycle_duration_ms = max(0.0, self.end_ms - self.start_ms)

    def ensure_backend_ready(self):
        """Pre-warm heavy playback backends before the sync barrier."""
        player = self.player
        try:
            prime = getattr(player, 'prime_for_sync_startup', None)
            if callable(prime):
                prime()
        except Exception:
            pass

        try:
            using_vlc = bool(
                hasattr(player, '_is_using_vlc_backend')
                and callable(player._is_using_vlc_backend)
                and player._is_using_vlc_backend()
            )
            if using_vlc and not bool(getattr(player, 'is_playing', False)):
                player.is_playing = False
                try:
                    player.play()
                except Exception:
                    pass
                try:
                    player.pause()
                except Exception:
                    pass
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

    def has_segment_loop(self) -> bool:
        return self.start_frame is not None and self.end_frame is not None

    def current_position_ms(self) -> float | None:
        player = self.player
        try:
            if hasattr(player, "_is_vlc_forward_active") and player._is_vlc_forward_active():
                position_ms = player._get_vlc_position_ms()
                if position_ms is not None:
                    return float(position_ms)
            elif hasattr(player, "_is_mpv_forward_active") and player._is_mpv_forward_active():
                position_ms = player._get_mpv_position_ms()
                if position_ms is not None:
                    return float(position_ms)
            else:
                return float(player.media_player.position())
        except Exception:
            pass

        try:
            if player.fps > 0:
                return (float(player.get_current_frame_number()) / float(player.fps)) * 1000.0
        except Exception:
            pass
        return None

    def freeze_at_end(self):
        if self.end_frame is None:
            return
        self.pause_hard()
        try:
            self.player.seek_to_frame(int(self.end_frame))
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
        self._warmup_index = 0
        self._warmup_batch_size = 0
        self._warmup_step_ms = 0

        # Barrier poll timer — only active during barrier phase.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_barrier)

        self._running_timer = QTimer(self)
        self._running_timer.setInterval(_POLL_INTERVAL_MS)
        self._running_timer.timeout.connect(self._poll_running)

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
            (e.cycle_duration_ms for e in self._entries), default=0.0
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

        self._state = self._STATE_WARMING
        self._warmup_index = 0
        if len(self._entries) >= _HEAVY_WARMUP_THRESHOLD:
            self._warmup_batch_size = _HEAVY_WARMUP_BATCH_SIZE
            self._warmup_step_ms = _HEAVY_WARMUP_STEP_MS
        else:
            self._warmup_batch_size = max(1, len(self._entries))
            self._warmup_step_ms = 0
        self._run_warmup_batch()

    def stop(self):
        self._poll_timer.stop()
        self._running_timer.stop()
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

    def _run_warmup_batch(self):
        if self._state != self._STATE_WARMING:
            return

        batch_end = min(len(self._entries), self._warmup_index + max(1, self._warmup_batch_size))
        for entry in self._entries[self._warmup_index:batch_end]:
            entry.ensure_backend_ready()
        self._warmup_index = batch_end

        if self._warmup_index < len(self._entries):
            QTimer.singleShot(max(0, int(self._warmup_step_ms)), self._run_warmup_batch)
            return

        QTimer.singleShot(_WARMUP_SETTLE_MS, self._on_warming_done)

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
        self._running_timer.stop()
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
                _sync_log(f"[SYNC] Barrier timed out after {elapsed:.0f}ms - firing anyway")
            else:
                _sync_log(f"[SYNC] Barrier passed after {elapsed:.0f}ms")
            self._poll_timer.stop()
            self._fire_play_all()

    # ------------------------------------------------------------------
    # Running — wait for all players to finish
    # ------------------------------------------------------------------

    @Slot()
    def _poll_running(self):
        if self._state != self._STATE_RUNNING:
            return

        for idx, entry in enumerate(self._entries):
            if entry.finished or not entry.has_segment_loop():
                continue

            position_ms = entry.current_position_ms()
            if position_ms is None:
                continue

            fps = max(1.0, float(entry.player.fps or 25.0))
            frame_ms = 1000.0 / fps
            late_margin_ms = max(1.0, min(10.0, frame_ms * 0.08))
            if position_ms < (entry.end_ms - late_margin_ms):
                continue

            _sync_log(f"[SYNC] segment end reached for player={idx} at {position_ms:.1f}ms")
            entry.freeze_at_end()
            entry.finished = True
            self._finished_count += 1

        if self._finished_count >= len(self._entries):
            _sync_log("[SYNC] all finished - beginning barrier")
            self._running_timer.stop()
            self._watchdog_timer.stop()
            self._state = self._STATE_BARRIER
            self._begin_barrier()

    @Slot()
    def _on_player_finished(self):
        sender = self.sender()
        idx = next((i for i, e in enumerate(self._entries) if e.player is sender), -1)
        already = self._entries[idx].finished if idx >= 0 else "?"
        _sync_log(
            f"[SYNC] playback_finished player={idx} already_finished={already} "
            f"state={self._state} count={self._finished_count+1}/{len(self._entries)}"
        )
        if self._state != self._STATE_RUNNING:
            return
        if idx >= 0 and self._entries[idx].finished:
            _sync_log(f"[SYNC] duplicate finished from player={idx} - ignoring")
            return
        self._finished_count += 1
        if idx >= 0:
            self._entries[idx].finished = True

        if self._finished_count >= len(self._entries):
            _sync_log("[SYNC] all finished - beginning barrier")
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
            _sync_log(f"[SYNC] Watchdog: {len(stalled)} player(s) stalled - forcing restart")
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
        _sync_log(f"[SYNC] firing play on {len(self._entries)} players")
        for entry in self._entries:
            entry.fire_play()
        self._running_timer.start()
        watchdog_ms = int(self._longest_duration_ms + _STALL_TIMEOUT_MS)
        if watchdog_ms > 0:
            self._watchdog_timer.start(watchdog_ms)
        _sync_log(f"[SYNC] watchdog set for {watchdog_ms}ms")
