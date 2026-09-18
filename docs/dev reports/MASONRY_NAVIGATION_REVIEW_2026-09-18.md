# Masonry navigation review — 2026-09-18

## Assessment

The strongest explanation is navigation/layout state losing agreement, rather than 26,848 images simply being too many. The system loads a bounded window, but several components independently decide which page owns the viewport and how its coordinates map to the scrollbar. Missing-page waits and recovery can then preserve the wrong state.

This is a source review against the supplied log, not a live reproduction. The exact failing event sequence and a regression-introducing commit remain unproven. No application code was changed. Existing working-tree changes, including main_window.py, were left intact.

The archived MASONRY_CURRENT_PROBLEMS_MATRIX.md and MASONRY_WINDOWED_STRICT_HANDOFF.md already describe deep-drag blank windows, tail failures, and repeated-drag drift. Those documents are historical evidence, not proof that every old defect remains. INDEX.md still points to their former locations.

## What the supplied log establishes

- The cached index contains 26,848 entries; asynchronous startup intentionally begins with zero resident pages. That line alone is not a failure.
- Background validation changes the dataset by 12 files and applies a model refresh. This is an important second state transition shortly after startup.
- Selection is restored at rank 9970. The corresponding code reports success after setting the current index and calling scrollTo; it does not verify that a real masonry tile actually intersects the viewport.
- The log does not identify the page requested by the failing drag, which pages completed, the accepted layout's target, or the count of real visible tiles. It cannot distinguish failed loading from loaded content positioned outside the viewport.

## Findings and priorities

### P1: Page ownership is resolved inconsistently

In image_list_view_scroll_mixin.py, _check_and_load_pages has consecutive `elif strict_mode and (not dragging_mode)` branches (around lines 509 and 532). The second, which resolves the transient owner anchor, is unreachable. The first branch consumes the condition even when it finds no waiting target.

MasonryWindowPlannerService.resolve_current_page does consult that transient anchor. Thus page loading and layout planning can choose different pages from the same view state. This is a confirmed control-flow defect; whether it triggers this specific incident needs reproduction.

The planner also applies raw top/bottom scrollbar clamps after resolving a drag anchor (around line 133). An intermediate Qt range clamp can therefore override an intended interior target. This is another ownership inconsistency worth testing directly.

Recommended work: one page-owner resolver used by loading, layout, paint recovery, and page indicators. Explicit current navigation intent must outrank stale geometry. Cover the unreachable branch and temporary scrollbar-edge conditions first.

### P1: Layout completion lacks a dataset/navigation identity check

MasonryCompletionService checks _masonry_mode_generation before installing worker results (lines 30–37), then replaces _masonry_items (around line 83). That generation changes on view-mode switching, not every navigation or dataset refresh. Submission passes geometry inputs and a cache key, without an immutable navigation/dataset generation attached to the completion contract.

Page loading already has _page_load_generation, including invalidation before background-refresh resets. Layout acceptance needs equivalent protection. An old-window layout completing during a new target or refreshed ordering is a plausible source of geometry/page mismatch even when page workers behave correctly.

Recommended work: carry an immutable layout request identity containing dataset/order generation, navigation generation, and geometry revision. Reject mismatched results before touching items, scroll range, anchors, or selection. Schedule the latest pending request after rejection.

### P1: Missing-target recovery can perpetuate itself

In image_list_view_calculation_mixin.py, _prepare_buffered_window_items waits for a nonempty target page. While an explicit jump remains active, each retry extends jump, restore, and release deadlines by another 15 seconds (around lines 193–207), then retries after 120 ms. Selection locks can also extend release locks. These deadlines do not provide a bounded failure exit.

The page request method returns immediately for any page already present in _pages, including an empty list. Consequently a resident empty page can be considered unready by layout while being considered already loaded by the request layer. That is a concrete no-progress state if encountered.

Recommended work: explicit page states (requested/loading/ready/empty/error), bounded retries based on progress, and a visible retry/error outcome. Do not silently teleport to an unrelated loaded page. Preserve target identity and keep usable content or meaningful placeholders visible while waiting.

### P1: Drag adds state changes before entering the working jump path

Drag release already calls go_to_global_index with `page_drag` (image_list_view_preload_mixin.py, around lines 592–611). Both page_drag and index_input dispatch to _start_one_shot_targeted_jump. Simply connecting drag to the index-jump function again would not address the problem.

Before that dispatch, drag handling changes the scroll domain, freezes it, sets anchors and edge locks, requests a buffered range, starts enrichment, changes selection bookkeeping, and toggles Qt grid sizing. Press and release also quantize positions to page boundaries for datasets larger than two pages. These differences explain why the same final jump helper can behave differently after a drag.

Recommended work: drag preview should record intent; release should submit one navigation request. Remove redundant loading/anchor transitions from the drag path as ownership is centralized. Explicitly decide whether dragging should select an image: the press comment promises selection preservation, while release changes selected-global bookkeeping.

### P2: Scrollbar and paint recovery remain competing writers

Range/value updates occur in scroll checking, geometry updates, layout completion, drag handling, and paint recovery. Paint recovery can reposition the scrollbar toward an anchor or nearest materialized tile. This makes rendering participate in navigation, with additional scroll callbacks and ownership decisions.

Recommended work: one controller owns range/value updates. Keep the global estimated domain separate from actual window-local tile coordinates, using explicit conversion. Painting should render the accepted snapshot and request recovery through the controller, without rewriting navigation state itself.

### P2: Extra page requests and obsolete queued work add pressure

_check_and_load_pages passes `(end_page + 1) * PAGE_SIZE` as the ending row. ensure_pages_for_range treats that endpoint as inclusive, so an interior seven-page window requests eight pages. Other callers correctly subtract one. The model then expands protection another page on each side. With the logged eight-page budget, these inconsistent window definitions complicate memory and eviction behavior.

cancel_pending_loads_except is explicitly a no-op. Prioritizing the target in a new submission batch does not move it ahead of already queued work from older navigation requests.

Recommended work: standardize range bounds, make target requests immediate, and debounce only speculative neighbors. Track queued futures and safely cancel obsolete work that has not started; running work may finish, but should not steal current ownership or evict the active target. Retain the existing protection against cancellation races.

### P2: Startup refresh and selection restoration need viewport-level verification

Background validation snapshots loaded pages, then _reload_paginated_model_after_db_update resets the model and reinstalls refreshed pages. Pages missing from the worker's snapshot can be loaded synchronously during apply. A user navigating while validation runs can therefore change which pages the UI needs before the refresh is installed.

The supplied rank-9970 restoration is relevant here. In main_window.py, _try_apply_safe_recenter checks several layout-busy attribute names, while masonry lifecycle uses _masonry_calculating. This deserves a focused audit: selection restoration success must not be equated with layout readiness.

Recommended work: carry the current viewport target through refresh by stable file identity, invalidate old layouts, and declare restoration complete only after target geometry is accepted and visible. Avoid synchronous missing-page reloads on the UI thread.

## Implementation sequence

1. Add a deterministic Qt event-loop reproduction using 27 logical pages and controlled worker completion order. Reproduce startup, delayed refresh, index jump, repeated drag, and tail-to-middle navigation.
2. Fix the unreachable owner branch, inclusive endpoint mismatch, and empty-page retry contract with focused tests.
3. Add dataset/navigation identities to layout jobs and reject stale completions. This creates a safe boundary for further simplification.
4. Consolidate drag/index/startup/refresh navigation into one state machine: target requested, page ready, layout ready, target visible, settled/error. Completion events should replace overlapping time-based locks.
5. Centralize coordinate/range ownership and make painting passive. Then optimize target-first scheduling, neighbor prefetch, and incremental layout caching.

Avoid starting with larger caches, more worker threads, longer lock durations, or more snap-to-nearest recovery. None resolves disagreement about which target is authoritative.

## Acceptance criteria

- A nonempty folder reaches a visible tile at startup without an extra click or jump.
- Repeat drag releases to pages 5, 18, 27, 14, and 2, including before prior loads complete; the newest target wins.
- Repeat while the delayed +12-file refresh applies and while dimensions arrive.
- Cover a partial last page, an empty/stale DB page, delayed or failed loads, zoom, and resize.
- An old layout never replaces a newer target or ordering.
- Once target data/layout are ready, at least one real target-window tile intersects the viewport; no indefinite loading state remains.
- Record request-to-first-visible-tile latency and longest UI stall. Measure before setting performance budgets.

Existing helper tests are useful, but mocked service tests alone cannot establish correctness across Qt range changes, worker callbacks, model resets, and paint timing. The key missing evidence is a repeatable end-to-end navigation sequence with controlled asynchronous ordering.

For diagnosis, use a small bounded event trace: navigation ID/reason, dataset generation, target page, requested/ready pages, layout submission/accept/reject, scroll value/range, and real visible tile count. Dump it on a no-progress timeout rather than logging every paint.
