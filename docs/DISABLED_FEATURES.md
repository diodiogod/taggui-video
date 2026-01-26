# Disabled Features

This document tracks features that have been temporarily disabled for testing or performance reasons.

## Cache Warming System (Disabled 2026-01-26)

**Reason:** Causes UI blocking during scrolling in large image folders (1M+ images)

**What was disabled:**
- Background cache warming that proactively generates thumbnails after scroll idle
- Cache status display in UI
- Automatic cache building in scrolling direction

**Files modified:**

### `taggui/widgets/image_list.py`
- Lines 416-419: `_cache_warm_idle_timer` initialization
- Lines 1830-1832: Timer start in scroll handler
- Lines 1845-1847: Timer stop in scrollContentsBy
- Lines 2552-2591: `_start_cache_warming()` method
- Lines 2593-2598: `_stop_cache_warming()` method
- Lines 2673-2678: Cache warm progress signal connection
- Lines 2698-2715: `_update_cache_status()` method

### `taggui/models/image_list_model.py`
- Line 255: `cache_warm_progress` signal definition
- Lines 301-303: `_cache_warm_executor` ThreadPoolExecutor
- Lines 326-332: Cache warming tracking variables (_cache_warm_cancelled, _cache_warm_futures, etc.)
- Lines 817-1020: `start_cache_warming()` method (entire method body)
- Lines 1022-1039: `stop_cache_warming()` method
- Lines 1179-1181: Cache warm progress emit in background save

**To re-enable:**
1. Search for `# DISABLED: Cache warming causes UI blocking` in both files
2. Uncomment all sections marked with this comment
3. Test with large datasets (1M+ images) to verify UI remains responsive

**Alternative approaches to consider:**
- Use lower priority threads (nice level)
- Add throttling/rate limiting to cache warming
- Only warm cache for visible page + next page (not entire folder)
- Use idle detection with longer delays (10+ seconds)
- Implement progressive cache warming over multiple sessions

## Force Cache Flush (Disabled 2026-01-26)

**Reason:** Causes complete UI freeze when queue reaches 300+ items

**What was disabled:**
- Automatic force flush when pending cache save queue exceeds 300 items
- This was causing UI to freeze completely, requiring app restart

**Files modified:**

### `taggui/models/image_list_model.py`
- Lines 1387-1390: Auto-flush when queue size >= 300

**Impact:**
- Cache saves will accumulate in memory during heavy scrolling
- Will be flushed when scrolling stops (normal behavior)
- Better to use more memory than freeze the UI

**To re-enable:**
1. Search for `# DISABLED: Force flush causes UI freeze` in model file
2. Consider implementing a non-blocking flush mechanism first
3. Options: async DB writes, separate thread for DB updates, or increase queue limit
