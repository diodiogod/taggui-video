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
- Double-click a thumbnail to perform the action selected in Advanced settings (floating viewer by default)
- Use `Ctrl` + double-click for the alternate floating-viewer or system-app action
- Open selected image in Windows Explorer: `Alt` + double-click
- Drag a real file to another app instead of spawning a floating viewer: hold `Alt` while dragging from the image list
- Drag a sibling workflow `.json` to another app when present, otherwise drag the media file: hold `Ctrl` + `Alt` while dragging from the image list
- Spawn a floating viewer by drag and release: drag a thumbnail from the list or masonry view and release it on empty screen space

The image context menu includes actions such as copying or pasting tags and moving or copying selected files.

Typing letters in the image list no longer jumps selection. Use the filter box when you want text-based searching.

### Generation prompts

Right-click an image or video and choose **Copy Positive Prompt** or **View Generation Prompt...**. The main and floating viewers also have prompt actions in their menus. Use the prompt window's arrows to browse the current list and update its viewer. Select text to copy just that part; multiple or unverified results require a manual choice. In Advanced settings, **Image double-click action** can also open the prompt viewer.

TagGUI reads saved positive metadata, including A1111 parameters, first; it then checks ComfyUI workflows embedded in the file or a matching `.json` sidecar. Simple Prompt is supported, though workflow inputs may differ from text changed at runtime, such as random choices. Video metadata reading requires `ffprobe` on `PATH` and recognizes VideoHelperSuite wrappers and [ComfyUI Video Saver](https://github.com/diodiogod/ComfyUI-Video-Saver) metadata. Reading happens only when requested and does not write to files, captions, or the database. A future opt-in batch import to captions or the database could be added separately.

The reader was informed by [Simple Readable Metadata](https://github.com/ShammiG/ComfyUI-Simple_Readable_Metadata-SG), [Prompt Manager](https://github.com/FranckyB/ComfyUI-Prompt-Manager), [SD Prompt Reader Node](https://github.com/receyuki/comfyui-prompt-reader-node), and [Prompt Viewer](https://github.com/Jasshl/ComfyUI-Prompt-Viewer).

## Main Viewer Fullscreen

- Toggle fullscreen for the main viewer: `F`
- Exit fullscreen: `Esc`
- Navigate previous or next media while fullscreen is active: `Left` / `Up` and `Right` / `Down`
- Open the fullscreen context menu: right-click the main viewer while fullscreen is active

Fullscreen applies to the main viewer only and works for both images and videos.

## Quick Sort

- Open or start the configured Quick Sort workflow: `Ctrl` + `Shift` + `Q`
- Sort to a matching folder with no setup: `A` to `Z` or `0` to `9`
- Skip the current item without moving or copying it: `Space`
- Undo or redo the last Quick Sort decision: `Ctrl` + `Z` / `Ctrl` + `Y`
- Alternate redo shortcut: `Ctrl` + `Shift` + `Z`
- Browse the immutable session queue: arrow keys, `Page Up`, `Page Down`, `Home`, or `End`
- Toggle the dedicated viewer fullscreen window: `F11`
- Clear a pending qualifier: `Backspace` or `Esc`
- Exit Quick Sort when no qualifier is pending: `Esc`

Quick Sort owns these keys only while its focused session is active. Named overrides and optional qualifier keys are configured in the Quick Sort panel.

## Image Tags Pane

- Add a tag: type in `Add Tag` and press `Enter`
- Add the first autocomplete suggestion: `Ctrl` + `Enter`
- Delete a tag: select it and press `Delete`
- Rename a tag: double-click it or press `F2`
- Reorder tags: drag and drop
- Select multiple tags: hold `Ctrl` or `Shift` and click
- Open the compact Text Transform window: `Ctrl` + `Shift` + `T`
- Apply the last configured Text Transform: `Ctrl` + `Alt` + `T`
- Open Text Transform from the pane: click the `⇄` title-bar button
- Open quick spatial corrections: right-click a highlighted spatial row or phrase
- Open the radial correction disk: left-drag a highlighted spatial phrase in either caption view

To add the same tag to multiple files, select the images first and then add the tag.

When the `Ideogram` mode is active, the same add, edit, delete, and reorder
interactions operate on structured caption rows. Selecting an element row also
selects its bounding box in the main viewer.

## Ideogram Regions

- Delete selected regions: `Delete` or `Backspace`
- Copy and paste selected regions: `Ctrl` + `C` / `Ctrl` + `V`
- Duplicate selected regions: `Ctrl` + `D`
- Undo the last recorded edit: `Ctrl` + `Z`
- Add regions to a multi-selection: `Ctrl`, `Shift`, or `Cmd` + click
- Move a region: drag inside it
- Resize a region: drag any edge or corner
- Convert object/text type: right-click a selected region

## All Tags Pane

- Show all images containing a tag: select the tag when `Tag click action` is set to `Filter images for tag`
- Add a tag filter with `AND`: `Ctrl` / `Cmd` + click a tag when `Tag click action` is set to `Filter images for tag`
- Add a tag filter with `OR`: `Alt` + click a tag when `Tag click action` is set to `Filter images for tag`
- Add a tag to selected images: click the tag when `Tag click action` is set to `Add tag to selected images`
- Delete all instances of a tag: select it and press `Delete`
- Rename all instances of a tag: double-click it or press `F2`

## Batch Operations

- Find and Replace: `Ctrl` + `R`
- Batch Reorder Tags: `Ctrl` + `B`
- Text Transform: `Ctrl` + `Shift` + `T`
- Apply Last Text Transform: `Ctrl` + `Alt` + `T`

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
- Open selection masonry wall: `Ctrl` + `Shift` + `Enter`
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

## Review Badges

- Apply numeric review badges: `1` to `5`
- Apply `*` badge: `8` or `Shift` + `8`
- Apply question badge: `?`
- Apply reject badge: `X`
- Apply warning badge: apostrophe/quote key
- Click badge buttons in the detachable `Review toolbar`
- Hover a masonry wall viewer and click the 3x3 badge slots
- Clear selected review badges: `Review toolbar -> Clear -> Clear Selected`
- Clear folder review badges: `Review toolbar -> Clear -> Clear Current Folder`

Badge shortcuts can be customized in `Settings -> Badges`.

When the pointer is over a still image in the main viewer, these shortcuts place
stickers at the cursor instead of toggling the image-level badge. Move the
pointer away from the image to use the normal toggle action.

## Image Stickers

| Control | Action |
| --- | --- |
| **Review badge shortcut over the main image** | Place that badge at the cursor. Repeat to add more stickers. |
| **L / B over the main image** | Animate a heart / bomb into a sticker at the cursor. |
| **L / B away from the main image** | Toggle Love / Bomb with the original reaction animation. |
| **Drag a review badge or reaction button onto the image** | Place a sticker where you release. |
| **Alt + right-click on the main image** | Choose a sticker at that point. |
| **Left-drag a sticker** | Move it. |
| **Alt + left-drag horizontally on a sticker** | Enlarge to the right; shrink to the left. |
| **Right-drag horizontally on a sticker** | The same resize gesture using the right mouse button. |
| **Right-click a sticker** | Replace it, remove it, or choose **Clear all stickers** for the image. |
| **Ctrl+Z / Ctrl+Y** | Undo / redo sticker edits, including clearing. |

Toolbar clicks retain their normal badge/reaction behavior. Turning a badge or
reaction off removes only its matching stickers. Floating viewers show saved
stickers; placement and editing belong to the main viewer.

See the [Stickers Guide](STICKERS_GUIDE.md) for rank fallback, appearance settings,
sidecar storage, and viewer support.

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
- Masonry review wall and badge workflow are documented in [Masonry Review Wall Guide](MASONRY_REVIEW_WALL_GUIDE.md).
- Detailed contextual video hover controls are documented in [Video Surface Controls Guide](VIDEO_SURFACE_CONTROLS_GUIDE.md).

## Continue Reading

- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Masonry Review Wall Guide](MASONRY_REVIEW_WALL_GUIDE.md)
- [Stickers Guide](STICKERS_GUIDE.md)
- [Compare Guide](COMPARE_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Text Transform and Spatial Caption Review Guide](TEXT_TRANSFORM_SPATIAL_REVIEW_GUIDE.md)
