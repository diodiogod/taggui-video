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

    def __init__(self, hold_seconds: float = 2.0):
        self.hold_seconds = max(0.1, float(hold_seconds))
        self._active = False
        self._source_key: str | None = None
        self._target_key: str | None = None
        self._target_blocked = False
        self._target_since = 0.0

    def begin_drag(self, source_key: str, *, now: float | None = None):
        now = time.monotonic() if now is None else float(now)
        self._active = True
        self._source_key = str(source_key or "")
        self._target_key = None
        self._target_blocked = False
        self._target_since = now

    def cancel_drag(self):
        self._active = False
        self._source_key = None
        self._target_key = None
        self._target_blocked = False
        self._target_since = 0.0

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

        if not target_key:
            self._target_key = None
            self._target_blocked = False
            self._target_since = now
            return self._state_snapshot(now=now, state="none")

        target_key = str(target_key)
        blocked = bool(blocked)
        if target_key != self._target_key or blocked != self._target_blocked:
            self._target_key = target_key
            self._target_blocked = blocked
            self._target_since = now

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
