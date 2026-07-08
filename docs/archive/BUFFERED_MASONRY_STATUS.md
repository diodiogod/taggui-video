# Buffered Masonry Pagination - Status Report

## Current Problem
TagGUI cannot handle 1M images efficiently. Loading all 1M Image objects (~300MB) into memory causes:
- UI sluggishness during all operations
- Qt managing 1M QModelIndex items (severe overhead)
- Masonry layout calculation taking 30+ seconds

## Goal
Implement **buffered virtual pagination**: Only load visible pages (3-20K images), dynamically load/unload as user scrolls, while maintaining smooth masonry layout view of full 1M dataset.

## What Works ✅

### Core Infrastructure
- **DB Caching**: ImageIndexDB stores dimensions, aspect ratios, paths (skip 1M file scan on reboot)
- **Page Loading**: Async loading of 1000-image pages from DB
- **LRU Eviction**: Keep max 20 pages in memory (~20K images)
- **Thumbnail Cache**: Disk cache + memory cache intact
- **Background Enrichment**: Dimension loading in background threads
- **Sorting via DB**: File name, modified time queries work across full 1M
- **Filtering**: Proxy model filtering still functional

### UI Elements
- **Scrollbar Range**: Correctly set to 19M pixels (representing 1M images)
- **Page Loading**: Pages load dynamically based on scroll position
- **Initial Display**: First 3 pages display immediately and correctly
- **Sort/Filter**: Works correctly across all 1M images via DB

## What's Broken ❌

### Primary Issue: Crashes on Scroll + Masonry Recalc
When user scrolls to new region:
1. Pages 497-503 load from DB (example)
2. System emits `layoutChanged` to recalculate masonry for new pages
3. **Qt C++ SEGFAULT** - likely during paint event processing

**Symptoms:**
- Crash happens between masonry recalc completion and enrichment resume
- No Python exception (segfault in Qt's event loop)
- Happens consistently when scrolling past initially loaded pages

### Secondary Issues
- **Images don't appear after scroll**: Masonry items only calculated for first 3 pages; when you scroll to page 500, no masonry positions exist for those items
- **Image count shows only loaded items**: Shows "Image 153 / 3000" instead of "/ 1,000,000 total"

## Architecture Issues

### Root Cause of Crashes
The conflict between:
1. **Qt's automatic layout management** - `updateGeometries()` wants to manage scrollbar based on `rowCount()` (3000 in our case)
2. **Our manual scrollbar management** - We set range to 19M pixels manually
3. **Dynamic page loading** - Emitting `layoutChanged` triggers Qt to recalculate, which conflicts with painting

When pages load and `layoutChanged` emits:
- Qt's event loop tries to access model state
- Concurrent page loading/eviction happening
- Paint event tries to find masonry positions for items in non-loaded pages
- **SEGFAULT**

### Design Flaw
Current approach assumes:
- Row 0 = first item in first loaded page
- Row N = Nth item across all loaded pages
- Masonry calculates positions for rows 0-N
- But when you scroll to page 500, those items aren't loaded → no masonry positions → nothing paints

This creates a fundamental conflict: **masonry needs to calculate for the items you're looking at, but those items only exist after pages load, which triggers layout changes that crash Qt**.

## What Was Tried

1. **Suppress masonry recalc during bootstrap** - Only recalc for first 3 pages, then silent page loads
   - Problem: Pages load silently, but masonry never updates for them
   - Result: Can't scroll to new regions

2. **Re-enable masonry recalc with debounce** - Recalc after 300ms of no page loads
   - Problem: Triggers Qt crashes
   - Result: Segfault

3. **Override Qt's updateGeometries()** - Manually restore scrollbar to 19M
   - Problem: Race condition with multiple timers/signals
   - Result: Still crashed

4. **Don't call viewport().update()** - Let Qt paint naturally
   - Problem: Crash happens in Qt's event loop before paint anyway
   - Result: Still crashed, but earlier debug messages appear

5. **Keep _masonry_total_height persistent** - Don't clear on layoutChanged
   - Problem: Helps scrollbar but doesn't solve the masonry/crash issue
   - Result: Scrollbar stable, but core crash remains

## Known Hurdles

### Qt Event Loop Fragility
- Qt's internal state management doesn't handle concurrent model changes well
- Emitting `layoutChanged` while pages are loading/evicting causes segfaults
- No Python-level exception handler can catch C++ segfaults

### Architectural Mismatch
- Masonry requires all item positions calculated upfront
- Virtual pagination requires loading items on-demand
- These two requirements conflict fundamentally in Qt's QListView

### Performance vs Correctness Trade-off
- Full masonry (Approach A): Calculate for all 1M items upfront → 30+ second UI freeze → Rejected
- Buffered masonry (Approach B): Calculate per-region → Crashes when switching regions
- No middle ground found that works with Qt's architecture

## Possible Next Steps

1. **Disable masonry recalc entirely after bootstrap** - Keep first-3-pages masonry, show blank for rest
   - Pro: No crashes
   - Con: Can't scroll smoothly through full dataset

2. **Use simpler grid layout instead of masonry** - Fixed cell sizes, no complex calculation
   - Pro: Qt can handle grid layout naturally
   - Con: Loses masonry's visual appeal

3. **Revert to Approach A with optimizations** - Full masonry but with better caching
   - Pro: Smooth scrolling through full dataset
   - Con: 30-second initial load (unacceptable)

4. **Implement true virtual scrolling** - Completely override Qt's painting/scrolling
   - Pro: Full control, can solve race conditions
   - Con: Massive refactor, high risk

## Files Modified
- `models/image_list_model.py` - Pagination logic, page loading
- `models/proxy_image_list_model.py` - Buffered aspect ratio collection
- `widgets/image_list.py` - Masonry calculation, scrollbar management, paint logic
- `utils/image_index_db.py` - DB queries for pagination

## Current Branch
`feature/buffered-masonry-approach-b` - WIP, unstable (crashes on scroll)
