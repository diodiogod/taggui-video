# Plan: Drag-to-Merge A/B Compare Mode for Main + Floating Viewers

## Summary
Implement a two-gesture compare workflow with hold-to-merge and animated target feedback.

Phase 1 delivers robust image compare with both gestures:
1. Thumbnail drag over target viewer (main or floating), hold 2.0s, release to compare.
2. Floating window drag over target viewer (main or floating), hold 2.0s, release to compare.

Phase 2 (separate follow-up) will add true live dual-video compare.
Phase 1 rejects video pairs with blocked feedback and preserves current fallback behavior.

## Scope and Locked Decisions
1. Gesture scope: support both thumbnail-over-window and window-over-window.
2. Target scope: main viewer and floating viewers are valid targets.
3. Hold rule: fixed 2.0 seconds.
4. Compare mapping: target media = left side, incoming media = right side.
5. Divider control: follows mouse X continuously.
6. Exit compare: Esc and context-menu action.
7. Invalid media in phase 1: reject merge with blocked animation; keep default behavior.
8. Hold incomplete: no compare; preserve existing spawn/move behavior.
9. Re-drop on active compare: replace right side only, keep left side and current split.
10. Window-source merge: close source floating window after successful merge.

## Public API and Interface Changes
1. Add compare APIs to `taggui/widgets/image_viewer.py`.
2. Add compare drag session coordinator methods to `taggui/widgets/main_window.py`.
3. Add floating-window drag compare signals in `taggui/widgets/floating_viewer_window.py`.
4. Add compare drag hooks in `taggui/widgets/image_list_view_interaction_mixin.py`.
5. Add reusable feedback overlay class `taggui/widgets/compare_drop_feedback_overlay.py`.
6. Add pure hold/target state logic in `taggui/widgets/compare_drag_coordinator.py`.
7. Add docs update in `docs/FLOATING_VIEWERS_USER_GUIDE.md`.

## Implementation Blueprint

### 1) Compare Drag State and Hold Logic
1. Create `taggui/widgets/compare_drag_coordinator.py` as a pure-logic coordinator.
2. Coordinator tracks source type, current target, hold start time, blocked state, ready state, and progress.
3. Coordinator output on each update: `none`, `hovering(progress)`, `blocked(progress)`, `ready`.
4. Release output: `handled_compare` or `fallback_default`.
5. Write unit tests for this class (no Qt dependency).

### 2) Target Feedback Animation
1. Create `taggui/widgets/compare_drop_feedback_overlay.py` as a global transparent overlay widget.
2. Draw animated border around target rect with:
3. Hover state: cyan pulse + progressive border fill (0→100% over hold).
4. Ready state: stronger glow/flash.
5. Blocked state: short red pulse.
6. Main window owns one overlay instance and updates its geometry/state from coordinator output.

### 3) Hook Thumbnail Drag Flow
1. In `taggui/widgets/image_list_view_interaction_mixin.py`, on `_begin_spawn_drag_active`, call main-window `begin_compare_drag_from_thumbnail(index)`.
2. During `_poll_spawn_drag_release`, call `update_compare_drag_cursor(QCursor.pos())`.
3. In `_finish_spawn_drag_active`, first call `release_compare_drag(global_pos)`.
4. If compare handled, skip spawning.
5. If not handled, keep current spawn behavior unchanged.
6. On cancel/leave/focus-loss cleanup, call `cancel_compare_drag()`.

### 4) Hook Floating Window Drag Flow
1. In `taggui/widgets/floating_viewer_window.py`, add signals for drag lifecycle:
2. `compare_drag_started(window)`
3. `compare_drag_moved(window, global_pos)`
4. `compare_drag_released(window, global_pos)`
5. `compare_drag_canceled(window)`
6. Emit these signals only for actual window-drag gestures (not resize).
7. In `taggui/widgets/main_window.py`, connect these signals when creating floating viewers.
8. On release, if compare handled, consume merge path and avoid any alternate fallback action beyond normal move completion.

### 5) Main Window Compare Session Integration
1. Add compare session state to `taggui/widgets/main_window.py`:
2. Active source descriptor.
3. Active target descriptor.
4. Coordinator instance.
5. Feedback overlay instance.
6. Implement target resolution by global cursor:
7. First top-level floating window under cursor (excluding source).
8. Else main viewer rect if visible and cursor inside.
9. Else no target.
10. Implement media eligibility check:
11. Phase 1 valid only when source and target are static images (`is_video == False`).
12. Invalid pair sets blocked state only.
13. Implement merge finalize:
14. Call target viewer `enter_compare_mode(base_index=target_current, incoming_index=source_index)`.
15. If source is floating window and merge succeeds, close source window.
16. Set active viewer to target viewer.
17. Hide overlay and clear session on completion/cancel.

### 6) ImageViewer Compare Mode
1. Extend `taggui/widgets/image_viewer.py` with compare session state and methods:
2. `is_compare_mode_active()`
3. `enter_compare_mode(base_index, incoming_index, keep_split_ratio=True)`
4. `replace_compare_right(incoming_index)`
5. `exit_compare_mode()`
6. `set_compare_split_from_view_x(x)`
7. Render approach:
8. Base image remains existing main pixmap item.
9. Incoming image is overlay pixmap item clipped by a scene rect clip item.
10. Vertical divider item tracks split position.
11. Default split at 50%.
12. Mouse-follow split:
13. In viewer event handling (view/viewport mouse move), if compare active, update split from current X.
14. Clamp split to viewport bounds.
15. Add “incoming image opens over target image” reveal animation when compare starts.
16. On re-drop while compare active, replace right item only and keep split ratio.
17. Exit compare with Esc via main-window shortcut and context-menu action.

### 7) Context Menus and Shortcuts
1. Add global Esc shortcut in `taggui/widgets/main_window.py` to exit compare on active viewer.
2. In `taggui/widgets/floating_viewer_window.py` right-click menu, add `Exit compare mode` when active.
3. In `taggui/widgets/main_window.py` main-viewer context-menu handler:
4. If compare active, show menu containing `Exit compare mode` plus existing spawn option.
5. If compare not active, preserve current quick spawn behavior.

### 8) Phase 2 Video-Compare Hooks (No Delivery in This Change)
1. Keep coordinator/source payload structure media-kind aware.
2. Keep compare entrypoint returning structured rejection reasons.
3. Add TODO notes in code where dual-video renderer will plug in later.

## Test Cases and Scenarios

### Automated
1. Add `tests/test_compare_drag_coordinator.py`:
2. Hold reaches ready exactly at 2.0s.
3. Target switch resets hold.
4. Leaving target clears hold.
5. Blocked pair never reaches ready.
6. Release before ready returns fallback.
7. Release while ready returns handled.
8. Add `tests/test_compare_target_resolution.py` (with small fakes):
9. Floating target precedence over main target.
10. Source window excluded from being target.
11. Hidden main viewer is not target.

### Manual QA
1. Thumbnail -> floating target, hold 2s, release: compare opens.
2. Thumbnail -> main target, hold 2s, release: compare opens.
3. Floating window -> floating target, hold 2s, release: compare opens and source window closes.
4. Floating window -> main target, hold 2s, release: compare opens and source window closes.
5. Release before 2s over valid target: no compare; default behavior remains.
6. Video-involved pair: blocked animation; no compare; fallback remains.
7. Re-drop on compare target: right side replaced, left side unchanged.
8. Divider follows mouse X smoothly.
9. Esc exits compare in both main and floating viewers.
10. Floating context menu shows `Exit compare mode` when compare active.

## Rollout and Compatibility
1. No data migrations.
2. No settings migration.
3. Existing spawn/move behavior remains default path when compare conditions are not met.

## Assumptions and Defaults
1. Phase 1 compare is view-only and image-only.
2. Live dual-video compare is explicitly deferred to phase 2.
3. Worktree path is `/mnt/j/Aitools/MyTagGUI/taggui_working`.
