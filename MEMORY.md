# TagGUI Project Memory

## Key Files
- `taggui/widgets/image_list.py` - 5100+ lines, main masonry/scroll/paint logic. Very large file.
- `taggui/widgets/masonry_layout.py` - Layout computation
- `taggui/widgets/masonry_worker.py` - Background worker
- `taggui/models/image_list_model.py` - Core paginated model

## Architecture: Windowed Strict Masonry
- `windowed_strict` strategy: scrollbar is a page selector, not pixel scroller
- Canonical domain controller: `_strict_canonical_domain_max()` is the single source of truth
- `_strict_page_from_position()` derives page from scroll value using canonical domain
- `_strict_virtual_avg_height` only grows, never shrinks (prevents domain drift)

## Key Lesson: Competing Writers Anti-Pattern
When multiple code paths independently compute and write to a shared resource (like a scrollbar range), each using different formulas over mutable state, the result is oscillation. Fix: single deterministic function that all callers use.

## Session 2 Investigation: Masonry 1:1 Rendering Bug (1M Dataset)
**Problem**: Far pages (20+, 100+, 240+) display images in 1:1 grid instead of masonry layout.

**Root Cause Identified** (not yet fixed):
- Four distinct column count formulas in the codebase:
  1. **Worker** (line 1245): `(viewport_width + spacing) // (col+spacing)` — MORE columns
  2. **Spacer** (line 1391): `(viewport_width - sb_width - 24) // (col+spacing)` — FEWER columns
  3. **Canonical domain** (line 733): Same as spacer
  4. **Avg_h calibration** (line 1858): Same as worker (formula mismatch!)
- When worker computes 9 columns but spacer/domain assume 8, prefix spacer height is wrong by ~500K pixels
- Items' Y coordinates don't reach as far as canonical domain expects, causing viewport gaps

**Scrollbar Visibility Drift**: `isVisible()` returns different values at different times (True during scroll, False at rest), causing ±1 column count variance between masonry calc and domain calc.

**Attempted Fixes** (all reverted):
1. **Translation layer** (`_strict_scroll_to_masonry_y`): Extrapolated from loaded items to unloaded target pages — produced garbage Y values when target pages weren't loaded
2. **Snap all pages immediately** (removed retry loop): Caused cascade as each snap triggered page loads around snap point → `pages_updated` → recalc → higher snap
3. **Column count consistency fix alone** (promising): Should work but needs careful testing

**Next Strategy** (for 1M dataset later):
- Apply column count consistency: all formulas use `(viewport_width - sb_width - 24) // (col+spacing)` where `sb_width = width or 15` (always-visible assumption)
- Test incrementally to avoid new cascades
- The retry loop waiting for target pages is OK — just needs the coordinate space alignment

## Project Docs
- `docs/INDEX.md` - File index
- `docs/MASONRY_WINDOWED_STRICT_HANDOFF.md` - Strict mode status
- `docs/MASONRY_CURRENT_PROBLEMS_MATRIX.md` - Repro scenarios
- `PLAN.md` - High-level implementation plan
