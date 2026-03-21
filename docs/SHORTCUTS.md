# Shortcuts

[Back to Documentation Hub](HUB.md)

This page collects the most useful keyboard shortcuts and quick actions currently documented for TagGUI Video 1M.

## Global

- Previous or next image: `Ctrl` + `Up` / `Down`
- Previous or next image fallback: `Up` / `Down`
- Previous or next image with mouse side buttons: mouse `Back` / `Forward`
- Jump to the first untagged image: `Ctrl` + `J`
- Focus `Filter Images`: `Alt` + `F`
- Focus `Add Tag`: `Alt` + `A`
- Focus `Image Tags`: `Alt` + `I`
- Focus `Search Tags`: `Alt` + `S`
- Focus `Start Auto-Captioning`: `Alt` + `C`

## Images Pane

- Jump to first or last image: `Home` / `End`
- Select multiple images: hold `Ctrl` or `Shift` and click
- Select all images: `Ctrl` + `A`
- Invert selection: `Ctrl` + `I`
- Duplicate selected images: `Ctrl` + `D`
- Open selected image in Windows Explorer: `Ctrl` + `E`
- Open image context menu: right-click an image
- Spawn a floating viewer from the clicked image: double-click
- Open the clicked image in its system default app: `Ctrl` + double-click
- Open selected image in Windows Explorer: `Alt` + double-click
- Drag a real file to another app instead of spawning a floating viewer: hold `Alt` while dragging from the image list
- Spawn a floating viewer by drag and release: drag a thumbnail from the list or masonry view and release it on empty screen space

The image context menu includes actions such as copying or pasting tags and moving or copying selected files.

Typing letters in the image list no longer jumps selection. Use the filter box when you want text-based searching.

## Main Viewer Fullscreen

- Toggle fullscreen for the main viewer: `F`
- Exit fullscreen: `Esc`
- Navigate previous or next media while fullscreen is active: `Left` / `Up` and `Right` / `Down`
- Open the fullscreen context menu: right-click the main viewer while fullscreen is active

Fullscreen applies to the main viewer only and works for both images and videos.

## Image Tags Pane

- Add a tag: type in `Add Tag` and press `Enter`
- Add the first autocomplete suggestion: `Ctrl` + `Enter`
- Delete a tag: select it and press `Delete`
- Rename a tag: double-click it or press `F2`
- Reorder tags: drag and drop
- Select multiple tags: hold `Ctrl` or `Shift` and click

To add the same tag to multiple files, select the images first and then add the tag.

## All Tags Pane

- Show all images containing a tag: select the tag when `Tag click action` is set to `Filter images for tag`
- Add a tag to selected images: click the tag when `Tag click action` is set to `Add tag to selected images`
- Delete all instances of a tag: select it and press `Delete`
- Rename all instances of a tag: double-click it or press `F2`

## Batch Operations

- Find and Replace: `Ctrl` + `R`
- Batch Reorder Tags: `Ctrl` + `B`

These actions are available from the `Edit` menu.

## Star Ratings

- Rate the current file with the painted toolbar stars
- Half-stars are supported: click the left or right half of a star, or drag across the widget and release
- Set rating with keyboard: `Ctrl` + `1` through `Ctrl` + `5`
- Clear rating with keyboard: `Ctrl` + `0`
- Create an exact star filter: `Ctrl` + click a toolbar star
- Create a minimum-star filter: `Ctrl` + `Shift` + click a toolbar star
- Toggle `love` and `bomb` from the toolbar reaction buttons

Examples:

- `Ctrl` + click on the 3-star button applies `stars:=3`
- `Ctrl` + click on the left half of the 4th star applies `stars:=3.5`
- `Ctrl` + `Shift` + click on the 3-star button applies `stars:>=3`

## Floating Viewers

- Spawn floating viewer: `Ctrl` + `Shift` + `N`
- Close all spawned viewers: `Ctrl` + `Shift` + `W`
- Toggle hold for existing spawned viewers: `H`
- Toggle hold for existing spawned viewers with the mouse: middle-click in the main window or image list area
- Move a floating viewer: `middle-click + drag`
- Move a non-pannable floating viewer: `left-drag`
- Resize a floating viewer: drag any edge or corner
- Keep floating viewer aspect ratio while resizing: hold `Shift`
- Close a floating viewer: click the hover `X` button near the top-right corner

Hold mode freezes existing spawned viewers as dimmed, gray, click-through overlays so you can keep using the main app and spawn new viewers without the older ones getting in the way.

## Floating Viewer Zoom and Compare

- Zoom in or out: mouse wheel
- Adaptive zoom in a floating viewer: left double-click
- Exit compare mode: `Esc`
- Open compare mode: drag a thumbnail onto a target viewer, hold for about 1 second, then release
- Expand or update an active compare view: drag another source onto the same compare target and hold again

## Contextual Video Surface Controls

- Hover lower left or lower right on a video with hidden controls: reveal contextual seek zones
- Click, double-click, or hold on a side seek zone: accumulate a seek burst
- Mouse wheel over a side seek zone: seek in the wheel direction
- Hover lower center on a video with hidden controls: reveal contextual scrub bar
- Click the contextual scrub bar: seek to that position
- Drag the contextual scrub bar: scrub through the video
- Hold the contextual scrub bar: temporary speed mode
- Double-click the contextual scrub bar: play/pause

## Floating Viewer Context Menu

- Sync videos: right-click a floating viewer and choose `Sync video`
- Close all spawned viewers: right-click a floating viewer and choose `Close all spawned viewers`
- Exit compare mode: right-click a floating viewer and choose `Exit compare mode` when compare mode is active

Floating viewers do not have their own fullscreen mode.

## Notes

- Floating viewer double-click zoom is adaptive, not a fixed single-step zoom.
- Detailed floating viewer behavior is documented in [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md).
- Detailed contextual video hover controls are documented in [Video Surface Controls Guide](VIDEO_SURFACE_CONTROLS_GUIDE.md).

## Continue Reading

- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Compare Guide](COMPARE_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
