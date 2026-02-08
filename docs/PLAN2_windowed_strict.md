# TagGUI 1M+ Paginated Masonry Plan

## Goal
Reach a stable, smooth image list that scales to very large datasets (100k to 1M+ files) without requiring global/full masonry recalculation.

## Current Baseline
- Branch baseline is stable-ish in `full_compat` behavior.
- Drag/scroll UX can still jitter or jump due to competing ownership between:
  - scrollbar fraction (virtual position),
  - visible masonry window (real painted items),
  - asynchronous page loads + eviction.
- Full/global masonry can still be triggered, which is not the final 1M+ architecture.

## Target Architecture
- Use **windowed masonry only** for paginated mode.
- Maintain **virtual scrollbar ownership** from dataset fraction.
- Keep non-window regions as virtual space (no global token expansion).
- Ensure paint/data loading never enters "empty dead zone" after drag release.

## Phases

### Phase 1: Control Plane (safe, no regression)
- Add explicit masonry strategy switch:
  - `full_compat` (default, current behavior),
  - `windowed_strict` (new progressive mode).
- Keep current baseline untouched by default.
- Add low-noise logs for active strategy/mode.

### Phase 2: Single Owner for Drag Mapping
- During drag + release, use scrollbar fraction as the only owner of target page/index.
- Freeze this target for a short settle window after release.
- Do not let visible masonry override target while settling.

### Phase 3: Window Contract + Spacer Contract
- Enforce one deterministic window contract:
  - target page +/- buffer.
- Always synthesize spacer coverage for non-loaded gaps inside active virtual span.
- Never allow viewport to render with no recoverable content path.

### Phase 4: Paint/Load Recovery Contract
- If viewport has no paintable tiles:
  - trigger deterministic targeted page loads for current target window.
  - keep one retry budget and then force a fallback window refresh.
- Avoid repeated blind-spot thrash loops.

### Phase 5: Eviction + Memory Stability
- Tie loaded-page cap strictly to eviction settings.
- Validate that page churn does not cause memory growth over time.
- Keep cache flush in background and decoupled from UI-critical paths.

### Phase 6: Validation Matrix
- Test scripts/scenarios:
  - start -> page 5 -> page 18 -> page 22 -> page 10 -> Home/End.
  - repeated drag without waiting for enrichment.
  - enrichment completion mid-session.
- Acceptance:
  - no jump-back on release,
  - no dead empty viewport,
  - no global/full masonry in `windowed_strict`,
  - smooth normal scrolling with bounded memory.

## Rules for Implementation
- Keep changes incremental and reversible.
- Preserve working baseline (`full_compat`) while building `windowed_strict`.
- Prefer deterministic state transitions over heuristic corrections.
