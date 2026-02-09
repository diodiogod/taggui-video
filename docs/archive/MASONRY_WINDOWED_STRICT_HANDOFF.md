# Masonry Windowed Strict - Handoff (Current State)

## Goal
Build a **true paginated/windowed masonry** flow that scales to very large datasets (100k to 1M+) without global/full masonry dependence.

## Current Mode Under Test
- Strategy: `windowed_strict`
- Main file: `taggui/widgets/image_list.py`
- Baseline comparison mode: `full_compat`

## What Is Working
- Startup and initial page rendering are stable.
- Drag to low/mid pages often loads target content correctly.
- Strict release mapping is generally better than earlier builds (less total chaos).
- Target-window preloading now happens on release.

## Current Critical Problems
1. **Thumb jump / ownership drift**
- Scroll thumb still jumps after release in many flows.
- Page ownership can change post-release due to range/domain churn.

2. **Empty viewport after deep drag (tail side)**
- Especially around page 18+ and bottom (20-22), list can go blank.
- UI shows `Loading target window...` and can remain stuck.

3. **Bottom behavior unstable**
- Reaching true bottom can create a state where drag up/down no longer maps cleanly.
- Sometimes only extreme top/bottom recovers content, middle stays blank.

4. **Range/domain inconsistency during drag**
- Strict logs show `Owner page` changing abruptly even when user drag intent is smooth.
- Release can map to unexpected pages after transient range changes.

## High-Signal Evidence Pattern (from user traces)
- Strict release says one target page, then owner/range moves rapidly after async page loads.
- `Waiting target page ...` appears repeatedly for strict windows.
- `Calc start ... mode=windowed_strict` alternates across distant windows soon after release.
- Tail flows (`page 18 -> 21`) are the most likely to hit blank viewport.

## Current Hypothesis (Primary)
The strict domain is still not fully single-source-of-truth. There are still competing updates between:
- virtual strict domain,
- real masonry-derived height/range,
- async page load completion + `pages_updated` + geometry refresh,
- release anchor / owner-page recomputation.

When these compete during/just after release, scroll range and ownership can de-sync, producing both thumb jumps and blank paint regions.

## Code Hotspots
- Strict drag capture + restore:
  - `_on_scrollbar_pressed`
  - `_on_scrollbar_slider_moved`
  - `_on_scrollbar_range_changed`
  - `_restore_strict_drag_domain`
  - `_on_scrollbar_released`

- Strict masonry completion + range writes:
  - `_on_masonry_calculation_complete`
  - `updateGeometries`

- Strict owner resolution and loading:
  - `_check_and_load_visible_pages`
  - paint fallback / void snap region ("Loading target window...")

## Hurdles / Constraints
1. Qt range/value updates are asynchronous and can clamp slider/value unexpectedly.
2. `pages_updated` events can arrive in bursts with partial window readiness.
3. Strict mapping requires stable virtual domain, but real masonry total height still influences flow.
4. Bottom/tail handling must include incomplete last page and loaded-page gaps.

## What Has Been Tried Already
- Drag baseline freezing and strict live fraction tracking.
- Range-restore guard during drag.
- Release lock + explicit target-window preload.
- Waiting for target page readiness before strict calc.
- Reduced strict owner-page spam logs.
- Attempted strict virtual domain normalization.
- Void snap recovery when nothing paints.

Result: improved from worst chaos, but not yet robust (still fails in deep/tail drag flows).

## Practical Repro Sequence (most useful)
1. Start app (paginated mode).
2. Drag release to page ~5 (should load and stabilize).
3. Drag release to page ~18.
4. Drag release to page ~21 (or very bottom).
5. Drag back to ~14.

Expected:
- No thumb jump.
- No empty viewport.
- Correct page ownership and content.

Actual:
- Jumping + occasional `Loading target window...` dead state.

## Minimal Logs to Keep
Only keep these while debugging strict mode:
- strict release line
- strict wait-target line
- strict calc-start line
- loading-target-window paint fallback line

All other verbose flow logs should stay off to reduce noise.

## Suggested Next Work Item
Move strict mode to a **single authoritative virtual domain controller** that is the only writer for scrollbar range in strict mode, and make owner page derive only from that domain during drag/release lock window.

Do not let masonry completion re-derive strict range from real-height paths during active strict sessions.
