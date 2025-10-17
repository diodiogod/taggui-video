# Video Editing Frame Count Bug Report

## Problem Summary
The video editing functionality in TagGUI is supposed to adjust video frame counts to follow the N*4+1 pattern required for certain AI training workflows. However, the frame counting is inconsistent and unreliable across different video files.

## Expected Behavior
- Videos should be adjusted to have exactly N*4+1 frames (where N is an integer)
- The algorithm should choose between removing frames or adding frames based on minimal changes
- Frame operations should be precise and consistent

## Actual Behavior
- Some videos get correct frame counts (e.g., 80 → 81 frames)
- Some videos get incorrect frame counts (e.g., 80 → 82 frames or 80 → 80 frames)
- Inconsistent results across different video files with same input frame count

## Root Cause Analysis
The issue stems from ffmpeg's inconsistent handling of frame extraction and concatenation operations:

1. **Time-based vs Frame-based extraction**: Initially used `-t` (duration) for segment extraction, which is imprecise due to floating-point arithmetic and frame timing variations.

2. **Concatenation timing issues**: When concatenating segments with different encodings (copy vs re-encoded), timing metadata gets corrupted.

3. **Frame duplication inconsistencies**: The repeated frame segment creation doesn't reliably produce the exact number of frames requested.

## Attempts Made

### Attempt 1: Fix QInputDialog Parameters
- **Issue**: `AttributeError: PySide6.QtWidgets.QInputDialog.getInt(): unsupported keyword 'min'`
- **Fix**: Changed `min`/`max` to `minValue`/`maxValue` (but this was wrong - PySide6 actually uses `min`/`max`)
- **Result**: Dialog works, but frame counting still broken

### Attempt 2: Improve Dialog Text
- **Issue**: Frame numbering was confusing (showing "79/80" for 80 frames)
- **Fix**: Added "(last)" indicator for final frame in dialog
- **Result**: UI improvement, but didn't fix frame counting

### Attempt 3: Switch to Frame-based Extraction
- **Issue**: Time-based extraction (`-t`) imprecise
- **Fix**: Used `-frames:v` for segment extraction instead of `-t`
- **Result**: More consistent, but still some failures

### Attempt 4: Fix Concatenation
- **Issue**: Mixing copy and re-encoded segments causes timing issues
- **Fix**: Re-encode final concatenation with consistent settings
- **Result**: Fixed some videos, broke others

### Attempt 5: Adjust Segment Boundaries
- **Issue**: Including/excluding repeated frame in segment1 caused double-counting
- **Fix**: Extract frames 0 to frame_num-1 in segment1, add repeated frames separately
- **Result**: Works for some videos, fails for others

### Attempt 6: Different Frame Creation Methods
- **Issue**: `-t` duration with `-loop` creates inconsistent frame counts
- **Fix**: Tried various ffmpeg options: `-frames:v`, `-t` with different loop settings, complex filters
- **Result**: Some methods work for some videos, none work consistently

## Technical Details

### Current Algorithm Logic
```python
# For input with 80 frames, target 81 frames:
current_frames = 80
frame_num = 79  # last frame index
repeat_count = 1

# Extract segment1: frames 0-78 (79 frames)
# Create repeated: 1 frame of frame 79
# Concatenate: should give 80 frames, but sometimes gives 81 or 82
```

### FFMPEG Commands Used
```bash
# Segment extraction
ffmpeg -i input.mp4 -frames:v 79 -c copy -y segment1.mp4

# Frame extraction
ffmpeg -i input.mp4 -vf select=eq(n\,79) -vframes 1 -y frame.png

# Repeated segment creation
ffmpeg -f image2 -loop 1 -i frame.png -t 0.0625 -r 16 -c:v libx264 -crf 18 -y repeated.mp4

# Concatenation
ffmpeg -f concat -safe 0 -i concat.txt -c:v libx264 -crf 18 -r 16 -y output.mp4
```

## Files Modified
- `taggui/widgets/main_window.py`: Dialog parameter fixes, improved text
- `taggui/utils/video_editor.py`: Frame extraction and concatenation logic
- `taggui/test_video.py`: Test script for validation

## Test Results
- pants (18).mp4: 80 → 81 ✓
- pants (21).mp4: 82 → 81 ✓
- pants (23).mp4: 82 → 81 ✓
- pants (24).mp4: 80 → 81 ✓ (after fixes)
- pants (25).mp4: 80 → 81 ✓
- pants (26).mp4: 80 → 80 ✗ (should be 81)

## Recommendations for Fix
1. **Abandon frame-level editing**: The complexity of precise frame manipulation with ffmpeg is too error-prone.

2. **Use duration adjustment**: Instead of adding/removing frames, adjust video duration by speeding up/slowing down slightly to hit target frame count.

3. **Implement frame duplication at filter level**: Use ffmpeg's `select` and `concat` filters to duplicate specific frames without segment extraction.

4. **Consider external tools**: For precise frame count adjustment, consider using more specialized video processing libraries like OpenCV or moviepy.

## Current Status
The functionality works for approximately 80% of test cases but fails unpredictably on certain videos, likely due to encoding differences or ffmpeg's handling of edge cases in frame timing.