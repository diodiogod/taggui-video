# Ghost Drag Alignment Handoff

## Goal
Make the spawn-drag ghost thumbnail follow the mouse in a predictable way.

Current desired UX:
- User clicks thumbnail, drags, releases.
- Ghost should appear **below mouse pointer** during drag.
- Spawned floating viewer should open where expected on release.

## Current Problem
Ghost position is wrong/inconsistent on this machine:
- Sometimes left-bottom of cursor.
- Sometimes right-bottom.
- Not reliably below/centered as intended.

User feedback: this should be simple and currently feels broken.

## Fast Repro
1. In image list/masonry, click a thumbnail.
2. Drag quickly and release.
3. Observe ghost position relative to cursor while dragging.

## Files Involved
- `taggui/widgets/image_list_view.py`
- `taggui/widgets/image_list_view_interaction_mixin.py`
- `taggui/widgets/image_list_view_geometry_mixin.py`

## Relevant Functions
- `ImageListViewInteractionMixin._begin_spawn_drag_active(...)`
- `ImageListViewInteractionMixin._poll_spawn_drag_release(...)`
- `ImageListViewInteractionMixin.mouseMoveEvent(...)`
- `ImageListViewGeometryMixin._show_spawn_drag_ghost(...)`
- `ImageListViewGeometryMixin._update_spawn_drag_ghost_pos(...)`
- `ImageListViewGeometryMixin._spawn_floating_for_index_at_cursor(...)`

## Important History (Already Tried)
- Multiple anchor strategies:
  - center on cursor
  - below cursor
  - below-right cursor
  - adaptive/compensation correction
- DPI-related sizing tweaks with `deviceIndependentSize()`.
- Window flag changes including `BypassWindowManagerHint`.
- Switched to arrow overlay at one point (worked visually), then reverted to ghost.
- Internal non-blocking drag flow was added to solve stuck fast-release bug.

## What Works Now
- Fast drag/release no longer gets stuck (major improvement).
- Spawn logic is stable.

## What Still Fails
- Ghost visual alignment to pointer remains wrong.

## Suspected Root Cause
Top-level tool-window ghost (`QLabel(None, Tool/Floating flags)`) may be platform/DPI/compositor-adjusted, causing unexpected screen-space placement vs cursor-space expectations.

## Constraints
- Keep fast drag/release reliability fix.
- Do not reintroduce stuck drag state.
- Keep behavior simple and predictable.

## Suggested Direction
Avoid top-level ghost window positioning quirks:
- Render ghost inside a full-screen transparent overlay widget in app coordinates, OR
- Render ghost in viewport coordinates (if acceptable) and map global cursor to viewport each frame.

Key idea: keep drawing in a coordinate space controlled by Qt layout/paint rather than WM-managed top-level helper window.

## Success Criteria
- Ghost consistently appears directly below pointer on every drag frame.
- Same behavior on slow and very fast drags.
- No stuck drag.
- Spawn location still feels consistent with pointer intent.

## Notes
- User asked to avoid overengineering. Prefer a minimal deterministic implementation.
