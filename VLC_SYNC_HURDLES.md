# VLC Multi-Window Sync: Hurdles and Attempt History

## Current State (Reverted)
- Branch: `feature/buffered-masonry-approach-b`
- Restored to committed checkpoint: `3cbc9c7` (`Stabilize video handoff and guard stale media items`)
- Reason for revert: recent uncommitted sync experiments caused regressions:
  - videos still not starting truly together,
  - sync sessions sometimes stopped looping,
  - occasional paused spawned window during sync.

## Goal
When user triggers **Sync Videos** across multiple spawned viewers:
1. All videos should start at the same perceived instant.
2. All videos should keep looping (with and without markers).
3. Sync should remain stable across loop boundaries.
4. Must support mixed durations (different clips in different windows).

## Persistent Problems Observed
- Start skew: windows start close, but not exactly together.
- Loop skew: one or more windows loop late/early.
- Some runs: loop fails after first pass (stops near end or pauses).
- In heavy multi-window sync: first-loop decode artifacts/black-frame flashes.
- Different-duration clips are harder to keep aligned than same-clip windows.

## What Was Tried

### 1) Sequential pause/seek/play sync
- Approach: pause all, seek all to start frame, then play each.
- Result: not simultaneous enough; startup skew remained.

### 2) Pre-roll API in `video_player.py`
- Added and used:
  - `prepare_for_sync_start(start_frame)`
  - `start_from_sync_ready(defer_reveal=True)`
  - `reveal_sync_started_playback()`
- Intent: preload each VLC instance paused at start, then start together.
- Result: improved smoothness in some cases, but true lock-step start still inconsistent.

### 3) Continuous sync timer with periodic corrections
- Approach: frequent follower seeks toward master timeline.
- Result: visible jitter/stutter, occasional "fighting" behavior, instability.
- Outcome: unsuitable for UX.

### 4) Boundary-only correction (reduced jitter)
- Approach: avoid constant correction; align mostly at startup and around loop boundary.
- Result: reduced jitter but still inconsistent starts and occasional de-sync.

### 5) Coordinator-owned looping
- Approach: disable per-player loop logic in sync mode; coordinator restarts all windows together at loop end.
- Result: unreliable triggers in practice; sometimes no re-loop after first pass.

### 6) Mixed-duration phase mapping
- Approach: map follower position by normalized phase of master loop.
- Result: conceptually correct, but did not solve real-world restart/timing instability.

### 7) Aggressive fail-safe wrap triggers
- Approach: detect near-end/stall/not-playing windows and force synchronized restart.
- Result: still unstable in user tests; regressions included non-looping sessions.

## Why This Is Hard in Current VLC Path
- Each embedded VLC instance has independent decode timing and EOF behavior.
- End-of-stream transitions are not perfectly deterministic across windows.
- "Soft" restarts avoid black flashes but are less deterministic.
- "Hard" restarts are deterministic but often cause visible black frame/flash.

## Practical Constraints from User
- Must prioritize correctness over elegance for sync mode.
- User accepts a stiffer/less pretty sync mode if it is deterministic.
- Loops must work with:
  - no markers (full-video loop),
  - marker ranges,
  - mixed-duration clips.

## Suggested Direction for Next LLM
Implement a **separate strict sync mode** (not normal playback path):
1. Use a single coordinator state machine.
2. Startup barrier:
   - pause all,
   - seek all to start,
   - wait until all report ready state,
   - start all on a scheduled timestamp.
3. Loop barrier:
   - coordinator alone decides loop wrap,
   - all players seek to loop start in one batch,
   - optional immediate play batch.
4. No continuous drift nudging during normal playback.
5. If strict mode is active, prefer deterministic behavior over visual smoothness:
   - allow controlled hard restart at boundaries if needed.
6. Consider a sync-quality toggle:
   - `Smooth` (best visual, weaker lock),
   - `Locked` (harder resets, stronger sync).

## Notes
- The reverted checkpoint (`3cbc9c7`) is stable for broader app usage, but does **not** deliver the requested robust multi-window VLC sync behavior.
- This document captures attempted approaches to avoid repeating the same patch cycle.
