# LLM Handoff: Zoom->Click Jump Bug (TagGUI)

## Branch / Base
- Branch: `feature/buffered-masonry-approach-b`
- Last committed base used during debugging: `c4127fb`
- Working tree is **dirty** (uncommitted changes from multiple attempts)

## Current Status
### Fixed
- Reboot restore now generally lands near/at intended item (improved from earlier state).
- Restore/path mapping robustness improved in paginated mode by validating path inside loaded page.

### Still Broken
- In masonry mode, after zooming, clicking an image still results in viewport/context drift.
- Symptom: first click can be correct, but subsequent click hits a different global tile because a recalc/resize pass runs in-between.
- **The selection jump does NOT require a second click.** A single click appears correct initially (correct `[CLICK-HIT]`), but then a recalc fires and the `[SAVE] Selected path:` changes to a DIFFERENT image. This means something AFTER the click is mutating the selection.

## Repro (current)
1. Open large folder in masonry mode.
2. Ctrl+wheel zoom.
3. Click a tile (looks correct initially).
4. A recalc pass runs (triggered by zoom debounce, enrichment, or dimensions_updated).
5. Selection silently changes to a different image.

## Expected vs Actual
- Expected: click selects the tile user clicked; selection stays stable through subsequent relayouts.
- Actual: click initially maps correctly, but a subsequent recalc mutates the selection to a different image.

## Key Recent Logs (Latest Attempt)
```text
[CLICK-HIT] global=175 proxy_row=175
[SAVE] Selected path: made-a-list-checked-it-twice-do-you-think-i-was-naughty-or-v0-k10jwf34h28g1.jpeg
[09:30:48.941][TRACE][ASPECT_RATIOS][DEBUG] Iterating loaded pages: 0-3 (4 pages)
[09:30:48.945][TRACE][MASONRY][DEBUG] Calc start: tokens=4000 window_pages=0-3 current_page=0 mode=windowed_strict
[RESIZE] Skipped stale queued recalc after user click
[MASONRY-INCR] Cache invalidated (4 pages): full_recalc:unknown
[09:30:49.523][TRACE][MASONRY][DEBUG] Calc start: tokens=4000 window_pages=0-3 current_page=0 mode=windowed_strict
[MASONRY-INCR] Cache invalidated (4 pages): full_recalc:unknown
[SAVE] Selected path: lounging-post-gym-v0-64rkjy7vcqgg1.jpg
```

### Critical Observation from Logs
- The `[CLICK-HIT]` correctly resolves global=175 to the intended image.
- `_skip_next_resize_recalc` fires ("Skipped stale queued recalc after user click") — so the FIRST resize recalc was blocked.
- But then **another** calc starts immediately (`full_recalc:unknown`), bypassing the skip guard.
- After that second recalc completes, `[SAVE] Selected path:` fires with a DIFFERENT image.
- **The selection mutation is NOT happening at click time. It's happening in the masonry completion handler or a signal cascade triggered by the recalc.**

## Files Modified (uncommitted)
- `taggui/models/image_list_model.py`
- `taggui/widgets/image_list_masonry_completion_service.py`
- `taggui/widgets/image_list_view.py`
- `taggui/widgets/image_list_view_geometry_mixin.py`
- `taggui/widgets/image_list_view_interaction_mixin.py`
- `taggui/widgets/image_list_view_paint_selection_mixin.py`

## What Was Tried (chronological, all failed)

### Attempt 1: Model mapping hardening
**Files**: `image_list_model.py`
- `get_index_for_path`: validates path inside loaded page instead of trusting rank offset blindly.
- `get_loaded_row_for_global_index`: bounds checks page length (pages can be shorter than PAGE_SIZE).
- **Result**: Did not fix. Problem is not in index mapping itself.

### Attempt 2: Click mapping hardening
**Files**: `image_list_view_interaction_mixin.py`
- Masonry click now tries global-geometry hit first (`global -> loaded row -> proxy`).
- Ignores click if `_masonry_calculating` is True or `_resize_timer` is active.
- **Result**: Did not fix. Click hit-test IS correct. The problem is post-click selection mutation.

### Attempt 3: Selection churn reduction
**Files**: `image_list_masonry_completion_service.py`, `image_list_view.py`
- Suppressed programmatic `setCurrentIndex` rebinding during resize/zoom anchoring (except restore).
- `_remember_selected_global_index` ignores transient updates during active masonry recalc/resize timer.
- **Result**: Did not fix. Selection mutation still happens through another path.

### Attempt 4: Skip next resize recalc after click
**Files**: `image_list_view.py`, `image_list_view_geometry_mixin.py`
- Added one-shot `_skip_next_resize_recalc` flag set on user click.
- `_on_resize_finished()` checks this flag and returns early once.
- **Result**: Partially works (log shows "Skipped stale queued recalc after user click"), but a SECOND recalc fires immediately after (triggered by `full_recalc:unknown` — likely from `_masonry_recalc_pending` or `dimensions_updated` signal), and THAT one mutates the selection.

### Attempt 5: Painted geometry snapshot for click hit-testing
**Files**: `image_list_view_paint_selection_mixin.py`, `image_list_view_interaction_mixin.py`, `image_list_view_geometry_mixin.py`, `image_list_view.py`
- During `paintEvent`, built `_painted_hit_regions` dict mapping `global_index -> QRect` for every rendered item.
- `mousePressEvent` resolves clicks against `_painted_hit_regions` (if <2s old) instead of `_masonry_items`.
- `indexAt()` also prefers the painted snapshot.
- Initialized in `__init__`, cleared on model reset.
- **Result**: Did not fix. This confirms the click hit-testing itself was NEVER the problem. The click resolves correctly every time. The issue is that something AFTER the click mutates the selection.

## Root Cause Analysis (Updated)

**The click hit-test is NOT broken.** Every attempt to fix the hit-test was misguided. The logs prove:
1. `[CLICK-HIT] global=175 proxy_row=175` — correct image identified
2. `[SAVE] Selected path: correct-image.jpeg` — correct image selected initially
3. Masonry recalc fires (from zoom debounce, enrichment, `dimensions_updated`, or `_masonry_recalc_pending`)
4. `[SAVE] Selected path: WRONG-image.jpg` — selection changed WITHOUT any user interaction

**The real bug is in the recalc completion path.** When masonry recalculation completes, something in the completion handler or its signal cascade is mutating the current selection. Likely candidates:

### Suspect 1: `_ensure_selected_anchor_if_needed()` in completion service
- Located in `image_list_masonry_completion_service.py`, inside `apply_and_signal()`.
- When `resize_anchor_live` is True (which it IS after zoom — `_activate_resize_anchor` sets a 4s hold), this function tries to re-select `_selected_global_index` and scroll to it.
- But if `_selected_global_index` was updated by `_remember_selected_global_index` during the recalc process (before the guard kicked in), it could contain a stale/wrong value.
- **Key question**: Is `_selected_global_index` getting corrupted between click and completion?

### Suspect 2: `_recenter_after_layout` scroll+select
- In `_on_resize_finished()`, `_recenter_after_layout` is set to `not strict_paginated`.
- In strict mode this should be False, but verify.

### Suspect 3: Signal cascade from `setCurrentIndex` in completion
- `setCurrentIndex` triggers `currentChanged` signal → `_remember_selected_global_index` → updates `_selected_global_index`.
- If the recalc shifted items and the "anchored" position now maps to a different global index, this creates a feedback loop.

### Suspect 4: The `[SAVE]` signal itself
- What triggers `[SAVE] Selected path:`? It's likely from `selectionChanged` or `currentChanged` signal on the view. If the completion handler calls `setCurrentIndex` (even for "anchoring"), it triggers `[SAVE]` with whatever image the new proxy index points to.

## What To Try Next (Priority Order)

### 1. TRACE THE [SAVE] TRIGGER
- Find what emits `[SAVE] Selected path:` and add a stack trace (`import traceback; traceback.print_stack()`) when it fires.
- This will immediately reveal which code path is mutating the selection after the click.

### 2. POST-CLICK SELECTION FREEZE
- After a user click, set a freeze flag (e.g., `_user_click_owns_selection_until = time.time() + 1.5`).
- In ALL code paths that call `setCurrentIndex` or modify selection (completion handler, anchor logic, recenter logic), check this flag and bail out if the user owns the selection.
- This is different from attempt 3 because it needs to cover ALL paths, not just the ones that were guarded.

### 3. AUDIT ALL setCurrentIndex CALLERS
- Grep for `setCurrentIndex`, `select(`, and `ClearAndSelect` across all mixins and services.
- Every call site that isn't directly from `mousePressEvent` needs a user-click ownership guard.

## Architecture Notes
- `image_list_view.py` is the main class shell, inherits 10 mixins + QListView.
- `image_list_masonry_completion_service.py` owns the post-recalc UI update lifecycle.
- `_remember_selected_global_index` (in `image_list_view.py`) is connected to `currentChanged` signal.
- `_on_resize_finished` (in `image_list_view_geometry_mixin.py`) is the resize debounce endpoint.
- `_calculate_masonry_layout` (in `image_list_view_calculation_mixin.py`) triggers async recalc.
- Completion flows: worker done → `on_masonry_calculation_complete` → `QTimer.singleShot(0, apply_and_signal)` → `_ensure_selected_anchor_if_needed()` + `_recenter_after_layout` logic.
