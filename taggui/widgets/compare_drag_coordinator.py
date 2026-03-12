"""Pure logic for hold-to-merge compare drag sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CompareTargetCandidate:
    """Candidate target used by pure target-priority resolution."""

    key: str
    kind: str  # "floating" or "main"
    order: int = 0
    metadata: object = None


def select_best_target(
    candidates: list[CompareTargetCandidate],
    *,
    source_key: str | None = None,
) -> CompareTargetCandidate | None:
    """Select best candidate: floating first, then highest order, excluding source."""
    filtered = [
        candidate
        for candidate in candidates
        if candidate.key and (source_key is None or candidate.key != source_key)
    ]
    if not filtered:
        return None

    def _priority(candidate: CompareTargetCandidate) -> tuple[int, int]:
        return (0 if candidate.kind == "floating" else 1, -int(candidate.order))

    filtered.sort(key=_priority)
    return filtered[0]


class CompareDragCoordinator:
    """Tracks one compare drag session with hold threshold and block state."""

    def __init__(self, hold_seconds: float = 2.0, movement_reset_distance: float = 96.0):
        self.hold_seconds = max(0.1, float(hold_seconds))
        self.movement_reset_distance = max(0.0, float(movement_reset_distance))
        self._active = False
        self._source_key: str | None = None
        self._target_key: str | None = None
        self._target_blocked = False
        self._target_since = 0.0
        self._target_anchor_pos: tuple[float, float] | None = None

    @staticmethod
    def _normalize_hover_pos(hover_pos) -> tuple[float, float] | None:
        if hover_pos is None:
            return None
        try:
            if hasattr(hover_pos, "x") and hasattr(hover_pos, "y"):
                return (float(hover_pos.x()), float(hover_pos.y()))
            x_value, y_value = hover_pos
            return (float(x_value), float(y_value))
        except Exception:
            return None

    def begin_drag(self, source_key: str, *, now: float | None = None):
        now = time.monotonic() if now is None else float(now)
        self._active = True
        self._source_key = str(source_key or "")
        self._target_key = None
        self._target_blocked = False
        self._target_since = now
        self._target_anchor_pos = None

    def cancel_drag(self):
        self._active = False
        self._source_key = None
        self._target_key = None
        self._target_blocked = False
        self._target_since = 0.0
        self._target_anchor_pos = None

    @property
    def active(self) -> bool:
        return bool(self._active)

    @property
    def source_key(self) -> str | None:
        return self._source_key

    def _state_snapshot(self, *, now: float, state: str) -> dict:
        if not self._target_key:
            elapsed = 0.0
            progress = 0.0
            ready = False
        else:
            elapsed = max(0.0, now - self._target_since)
            progress = min(1.0, elapsed / self.hold_seconds)
            ready = (not self._target_blocked) and progress >= 1.0

        return {
            "state": state,
            "progress": progress,
            "ready": ready,
            "blocked": bool(self._target_blocked),
            "target_key": self._target_key,
            "source_key": self._source_key,
        }

    def update_target(
        self,
        target_key: str | None,
        *,
        blocked: bool = False,
        hover_pos=None,
        now: float | None = None,
    ) -> dict:
        now = time.monotonic() if now is None else float(now)
        if not self._active:
            return {
                "state": "none",
                "progress": 0.0,
                "ready": False,
                "blocked": False,
                "target_key": None,
                "source_key": None,
            }

        normalized_hover_pos = self._normalize_hover_pos(hover_pos)
        if not target_key:
            self._target_key = None
            self._target_blocked = False
            self._target_since = now
            self._target_anchor_pos = None
            return self._state_snapshot(now=now, state="none")

        target_key = str(target_key)
        blocked = bool(blocked)
        if target_key != self._target_key or blocked != self._target_blocked:
            self._target_key = target_key
            self._target_blocked = blocked
            self._target_since = now
            self._target_anchor_pos = normalized_hover_pos
        elif (
            normalized_hover_pos is not None
            and self._target_anchor_pos is not None
            and self.movement_reset_distance > 0.0
        ):
            dx = normalized_hover_pos[0] - self._target_anchor_pos[0]
            dy = normalized_hover_pos[1] - self._target_anchor_pos[1]
            if ((dx * dx) + (dy * dy)) >= (self.movement_reset_distance * self.movement_reset_distance):
                self._target_since = now
                self._target_anchor_pos = normalized_hover_pos

        state = "blocked" if self._target_blocked else "hovering"
        snapshot = self._state_snapshot(now=now, state=state)
        if snapshot["ready"]:
            snapshot["state"] = "ready"
        return snapshot

    def release_drag(self, *, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else float(now)
        if not self._active:
            return {"handled": False, "target_key": None, "state": "none"}

        elapsed = max(0.0, now - self._target_since)
        handled = bool(self._target_key) and (not self._target_blocked) and elapsed >= self.hold_seconds
        target_key = self._target_key
        state = "ready" if handled else ("blocked" if self._target_blocked else "hovering")
        self.cancel_drag()
        return {"handled": handled, "target_key": target_key, "state": state}
