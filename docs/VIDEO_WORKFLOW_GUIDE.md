# Video Workflow Guide

Video support in TagGUI Video 1M starts with simple playback, but the real value is in review, comparison, extraction, and training-preparation workflows.

## Start with Playback

The basic video workflow is simple:

1. Load a folder that contains videos.
2. Click a video in the image list.
3. If autoplay is enabled, playback starts automatically.
4. Use the timeline, frame controls, loop markers, and speed controls to inspect the clip.

This makes TagGUI a practical video media viewer even before you use the editing tools.

## Core Video Workflows

The main video tasks supported by the current project are:

- play and inspect videos inside the main viewer
- navigate by timeline and frames
- set loop ranges for review or extraction
- compare multiple videos visually
- sync multiple spawned video viewers
- extract precise clips or rough keyframe-based clips
- prepare datasets for training workflows
- fix broken video metadata issues such as frame-count or SAR problems

## Loop Markers and Timeline

Loop markers are a central part of the video workflow.

You can use them to:

- mark a segment for repeated playback
- define the range to extract
- define the range to remove
- define the range to use for comparison or timing checks

- drag a loop marker to move it
- `Shift` + drag a loop marker to move both markers together
- clicking the timeline jumps position
- dragging markers previews position while you adjust them
- loop markers are persistent, so they are restored when you load the file again

Loop work is especially important for dataset preparation, because it gives you direct frame-range control before editing.

## Playback Speed and Reverse

Playback speed is part of the normal video workflow.

Use it to:

- slow down motion for inspection
- speed up review of long clips
- prepare extraction choices before editing

> [!NOTE]
> Reverse playback exists and is useful for inspection and clip-preparation workflows.

## Extraction and Editing

TagGUI Video 1M includes real video editing operations, not just playback controls.

Supported editing actions include:

- rough extract
- precise extract
- remove range
- remove single frame
- repeat single frame
- frame-count fixes
- SAR fixes
- undo video edit
- redo video edit

### Rough Extract

Rough extract is the fast option.

- no re-encode
- preserves quality
- cuts at nearby keyframes
- useful for rough trimming and fast dataset prep

### Precise Extract

Precise extract is the frame-accurate option.

- re-encodes the clip
- uses the marked range exactly
- supports optional reverse extraction
- supports optional speed and FPS changes during extraction

This is the better path when exact frame count matters.

## Dataset Preparation Workflows

One of the main reasons to use TagGUI Video 1M is preparing clips for model training workflows.

That includes tasks such as:

- extracting exact frame ranges
- choosing a specific FPS
- targeting a specific frame count
- checking whether a clip matches required frame-count patterns such as `N*4+1`
- fixing broken clips before training use

This is one of the places where the project goes well beyond a normal media viewer.

## Multi-Viewer and Sync Workflows

Spawned viewers are useful for video comparison and side-by-side review.

Typical workflow:

- spawn extra viewers
- load or route different videos into them
- compare motion or timing visually
- sync the viewers when needed

Important behavior:

- one viewer is the active controls owner at a time
- right-click actions include `Sync video`
- sync is useful for comparison, even if it should not be described as perfectly frame-accurate

Detailed viewer behavior is documented in `FLOATING_VIEWERS_USER_GUIDE.md`.

## Video Comparison

Video comparison is supported, not just image comparison.

To create a compare:

- drag one media item onto a target viewer
- hold for about 1 second
- wait for the target feedback to appear
- release to enter compare mode

This compare gesture is used for both image and video comparison workflows.

- 2-video comparison
- 3-video comparison
- 4-video comparison
- image comparison
- image-to-image drag/drop compare
- video-to-video compare window workflows

For video comparison, the compare window also exposes fit-mode options such as:

- `Preserve Aspect Ratio`
- `Fill (Crop)`
- `Stretch (Distorts)`

This makes the compare tools useful for visual inspection, timing comparison, and general clip review.

## Backends

> [!NOTE]
> MPV is the recommended playback backend.

Other backend paths exist and may still be useful, but they do not behave identically.

> [!WARNING]
> VLC works, but it does not provide the same frame-accuracy behavior for loops and markers. If exact loop timing matters, that difference is important.

## Related Docs

- Floating viewers behavior: `FLOATING_VIEWERS_USER_GUIDE.md`
- Filtering and sorting: `FILTERING_GUIDE.md`
- Captioning: `CAPTIONING_GUIDE.md`
- Skin system details: `SKIN_DESIGNER_GUIDE.md`
