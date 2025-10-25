# Video Operation Queue Implementation Plan

## Problem Statement

Current video editing architecture applies operations sequentially with separate ffmpeg calls, causing:
- Multiple generations of compression artifacts (each re-encode degrades quality)
- No preview of combined effects before applying
- Messy backup chains from successive operations
- Poor user experience (no undo, no planning)

**This critically affects AI training data quality.**

## Solution: Operation Queue System

Implement a staging/queue system that batches multiple operations into a single ffmpeg call with combined filters.

## Architecture Overview

```
User Action → Operation Queue → Preview → Single FFmpeg Render
     ↓              ↓              ↓              ↓
  (Stage)      (Accumulate)   (Validate)    (One encode)
```

## Files to Create

### 1. `utils/video/operation_queue.py` (~250 lines)

```python
class VideoOperation:
    """Base class for video operations"""
    type: OperationType  # CROP, FPS, SPEED, EXTRACT, REMOVE, REPEAT
    params: dict

    def to_filter(self) -> str:
        """Convert to ffmpeg filter string"""

    def affects_frame_count(self) -> bool:
        """Does this change number of frames?"""

    def get_priority(self) -> int:
        """For optimal filter ordering"""

class CropOperation(VideoOperation):
    # crop=w:h:x:y

class FPSOperation(VideoOperation):
    # fps=N

class SpeedOperation(VideoOperation):
    # setpts=PTS/FACTOR

class FrameOperation(VideoOperation):
    # For extract/remove/repeat - may need separate handling

class OperationQueue:
    """Manages pending operations"""
    operations: List[VideoOperation]

    def add(self, operation: VideoOperation)
    def remove(self, index: int)
    def clear()
    def reorder()  # Auto-optimize order

    def build_filter_chain(self) -> str:
        """Returns combined ffmpeg -filter:v string"""
        # Example: "crop=1280:720:0:0,setpts=PTS/1.5,fps=16"

    def estimate_output_specs(self, input_video: VideoInfo) -> VideoInfo:
        """Calculate final resolution, fps, duration, frame count"""

    def validate(self) -> List[str]:
        """Check for conflicts/warnings"""
        # e.g., "Speed change before FPS may cause temporal artifacts"

    def execute(self, input_path: str, output_path: str, quality: str = "high"):
        """Run single ffmpeg command with all filters"""
```

**Key Logic:**
- Filter ordering priority: CROP(1) → SCALE(2) → SPEED(3) → FPS(4) → COLOR(5)
- Frame operations (extract/remove/repeat) may need separate pass or complex filter
- Support "preview mode" with sample encode (first 5 seconds)

### 2. `widgets/video_operations_panel.py` (~200 lines)

```python
class VideoOperationsPanelWidget(QWidget):
    """UI panel showing queued operations"""

    operation_queue: OperationQueue

    # Widgets:
    - QListWidget: Shows pending operations with icons
    - QPushButton: "Apply All", "Clear Queue", "Preview"
    - QLabel: Shows original → final specs

    def add_operation_to_list(self, op: VideoOperation):
        """Add visual item to list"""

    def update_preview_info(self):
        """Update specs display (resolution, fps, duration, frames)"""

    def show_warnings(self):
        """Display validation warnings"""

    def on_apply_clicked(self):
        """Execute queue and clear"""

    def on_preview_clicked(self):
        """Render sample (first 5s) to temp file and show"""
```

**UI Layout:**
```
┌─ Pending Operations ────────────────┐
│ 1. Crop to 1280x720                 │
│ 2. Change speed to 1.5x             │
│ 3. Change FPS to 16                 │
│                                      │
│ [↑] [↓] [Remove] [Clear All]        │
├──────────────────────────────────────┤
│ Original:  1920x1080, 30fps, 300fr  │
│ Final:     1280x720,  16fps, 200fr  │
│ Duration:  10.0s → 6.67s            │
├──────────────────────────────────────┤
│ [Preview Sample] [Apply All Changes] │
└──────────────────────────────────────┘
```

### 3. `utils/video/video_info.py` (~100 lines)

```python
@dataclass
class VideoInfo:
    """Video specifications"""
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: str
    bitrate: int

    @staticmethod
    def from_file(path: str) -> VideoInfo:
        """Extract info using ffprobe"""

    def apply_operation(self, op: VideoOperation) -> 'VideoInfo':
        """Calculate new specs after operation"""
```

## Files to Modify

### 4. `controllers/video_editing_controller.py`

**Changes:**
- Add `self.operation_queue = OperationQueue()`
- Modify `crop_video()`, `change_fps()`, `change_speed()` to:
  - Create operation object
  - Add to queue instead of immediate execution
  - Update UI to show pending state
- Add `apply_queued_operations()` method
- Add `clear_operation_queue()` method

```python
def crop_video(self):
    # OLD: Immediate execution
    # backup_path = create_backup(video_path)
    # run_ffmpeg(crop_filter)

    # NEW: Queue operation
    crop_op = CropOperation(params={'w': w, 'h': h, 'x': x, 'y': y})
    self.operation_queue.add(crop_op)
    self.operations_panel.update_display()

def apply_queued_operations(self):
    """Execute all pending operations in one ffmpeg call"""
    backup_path = create_backup(video_path)
    try:
        self.operation_queue.execute(video_path, temp_output)
        replace_video_safely(video_path, temp_output)
        self.operation_queue.clear()
    except Exception as e:
        restore_backup(backup_path)
        raise
```

### 5. `widgets/main_window.py`

**Changes:**
- Add `VideoOperationsPanelWidget` to UI layout
- Connect to `video_editing_controller.operation_queue`
- Add to Video menu: "Apply Pending Operations", "Clear Queue"

```python
# In __init__
self.operations_panel = VideoOperationsPanelWidget(self)
self.video_editing_controller.set_operations_panel(self.operations_panel)

# Layout: Add panel below video controls or as dockable widget
```

### 6. `utils/video/frame_editor.py`

**Minor refactor:**
- Extract filter string generation into separate functions
- Make functions accept optional `extra_filters` parameter for chaining
- Add `execute_filter_chain()` helper

```python
def build_crop_filter(w: int, h: int, x: int, y: int) -> str:
    return f"crop={w}:{h}:{x}:{y}"

def build_fps_filter(fps: float) -> str:
    return f"fps={fps}"

def build_speed_filter(factor: float) -> str:
    return f"setpts=PTS/{factor}"

def execute_filter_chain(input_path: str, output_path: str,
                         filter_chain: str, quality: str = "high"):
    """Single ffmpeg call with combined filters"""
    crf = {"high": 18, "medium": 23, "low": 28}[quality]

    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter:v', filter_chain,
        '-c:v', 'libx264', '-crf', str(crf), '-preset', 'medium',
        '-c:a', 'copy',
        output_path
    ]
    subprocess.run(cmd, check=True)
```

## Implementation Phases

### Phase 1: Core Queue System (2-3 hours)
1. Create `VideoInfo` dataclass with ffprobe integration
2. Create `VideoOperation` base class and subclasses (Crop, FPS, Speed)
3. Create `OperationQueue` with filter chain building
4. Write unit tests for filter generation

### Phase 2: UI Integration (2 hours)
1. Create `VideoOperationsPanelWidget`
2. Integrate into `main_window.py`
3. Connect to existing video editing triggers

### Phase 3: Controller Refactor (2 hours)
1. Modify `VideoEditingController` to use queue
2. Add "stage mode" vs "immediate mode" toggle (for backward compat)
3. Update menu actions

### Phase 4: Advanced Features (Optional, 2-3 hours)
1. Preview rendering (encode first 5 seconds)
2. Operation reordering UI (drag-drop in list)
3. Save/load operation presets
4. Batch apply to multiple videos

### Phase 5: Frame Operations (Complex, 3-4 hours)
Handle extract/remove/repeat frames - these may need:
- Separate ffmpeg pass (can't easily combine with filters)
- Or complex select filter: `select='between(n,10,20)'`
- May require hybrid approach: frame ops first, then filter chain

## Quality Settings

Recommended ffmpeg encoding params for queue execution:

```python
QUALITY_PRESETS = {
    'high': {
        'crf': 18,
        'preset': 'slow',
        'profile': 'high',
    },
    'medium': {
        'crf': 23,
        'preset': 'medium',
        'profile': 'main',
    },
    'low': {
        'crf': 28,
        'preset': 'fast',
        'profile': 'main',
    }
}
```

## Edge Cases & Challenges

### 1. Frame Operations (extract/remove/repeat)
These modify frame sequences, harder to combine with filters:
- **Option A**: Execute frame ops first, then apply filter chain
- **Option B**: Use complex select filter (limited flexibility)
- **Recommendation**: Two-pass system if queue contains frame ops

### 2. Audio Handling
- Speed changes affect audio (`atempo` filter)
- FPS changes don't (audio copy)
- Need audio filter chain builder too

### 3. Operation Conflicts
- Detect: "Extract frames 1-10" then "Change FPS" (which applies first?)
- Validation warnings needed

### 4. Undo/Redo
- Current backup system creates `.bak` files
- With queue, only one backup before "Apply All"
- May want operation history for undo (keep queue states)

## Testing Strategy

1. **Unit tests** for filter generation:
   - `test_crop_filter_string()`
   - `test_combined_filters()`
   - `test_operation_ordering()`

2. **Integration tests**:
   - Apply crop + fps + speed, verify single encode
   - Check output specs match predictions

3. **Manual testing**:
   - Visual quality comparison (multi-encode vs single-encode)
   - UI workflow testing

## Backward Compatibility

- Keep "immediate mode" as option in settings
- Or: Auto-apply queue if only one operation (seamless migration)
- Preserve existing backup system

## Success Metrics

- ✅ Single ffmpeg call for multiple operations
- ✅ No quality degradation from operation chaining
- ✅ Preview shows accurate final specs
- ✅ UI clearly shows pending vs applied operations
- ✅ Backup system still works (one backup per batch)

## Future Enhancements

- Batch apply queue to multiple videos
- Save operation chains as presets ("Prepare for training: crop 512x512, 16fps, 2x speed")
- GPU acceleration for encoding (`-c:v h264_nvenc`)
- Progress bar for long encodes
- Cancel operation mid-encode

## Notes

- This is **critical for data quality** - prioritize over new features
- Affects training dataset integrity (fewer compression artifacts)
- Improves UX (plan operations, preview, undo-friendly)
- Architecture scales to future operations (filters, color grading, etc.)
