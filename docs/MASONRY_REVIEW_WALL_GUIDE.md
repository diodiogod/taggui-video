# Masonry Review Wall Guide

[Back to Documentation Hub](HUB.md)

This guide covers the Masonry Wall layout and the review badge workflow.

It is designed for fast comparison of multiple images or videos in separate floating windows, especially when you want to sort many similar generations and mark picks, rejects, questions, or custom badge meanings.

## What It Is

- The Masonry Wall can open the current selection or rearrange the current floating windows as one wall.
- It keeps the top aligned and packs the windows in a masonry-style arrangement across the current screen.
- Mixed images and videos are supported.
- If the wall contains multiple videos, video sync and playback start automatically.
- The wall works together with the review badge system, so you can mark files while comparing them.
- The shared masonry spacing can be adjusted in `Settings -> Advanced -> Floating masonry wall gap (px)`.
- Horizontal alignment can be adjusted in `Settings -> Advanced -> Floating masonry alignment`.
- Right-click a wall window and toggle `Masonry wall controls` live.

<p align="center">
  <img src="../images/masonry-review-wall.jpg" alt="Masonry review wall with review badges" width="86%">
</p>

## Open The Masonry Wall

- Select two or more items in the image list.
- Right-click and choose `Open ... in Masonry Wall`.
- Or press `Ctrl` + `Shift` + `Enter`.
- Or drag a multi-selection from the image list and release it to open the wall directly.

Single-item spawn is still available. The masonry wall is for multi-item review.

## Arrange Existing Floating Windows

- Right-click a floating viewer or comparison window and choose `Arrange as Masonry Wall`.
- This repacks the current floating windows into the same Masonry Wall layout.
- Rearranging starts with the wall controls off.
- Turn them on later from the window right-click menu if needed.

## Why Use It

- Compare many similar generations at once.
- Review short video variants side by side.
- Keep the main window available while using floating viewers for decisions.
- Mark picks and rejects without leaving the comparison workflow.

## Packing and Automatic Reflow

Right-click a wall window and open **Wall layout**:

| Menu entry | What it does |
| --- | --- |
| Arrange now | Fit the current wall while respecting its locks. |
| Arrange automatically after resizing | Apply a new layout on resize release. This is one saved on/off setting, also toggled with Ctrl+Alt+M. |
| This window | Choose **Flexible**, **Keep size**, or **Pin in place**. Exactly one state is shown. |
| Reset layout | Release kept sizes, unpin all windows, or start fresh by releasing all locks and arranging. |
| Packing algorithm (this session) | Keep testing Best fit, Masonry, or MaxRects without changing your saved default. |
| Wall settings… | Open grouped preferences with explanations. They also appear in Settings -> Advanced -> Floating Wall Layout. |

Under **This window**, Flexible releases all of that window's locks; Keep size
allows movement but preserves its dimensions; Pin in place preserves both.
Manual resizing automatically changes a flexible window to Keep size when
**Remember sizes I change** is enabled. Ctrl-drag changes it to Pin in place.
Window locks last until released or the window closes.

**Reset layout -> Release kept sizes** retains pins. **Unpin all windows** retains
separate size locks. Neither immediately moves windows. **Start fresh — release all
locks and arrange** removes both constraints and fits again, even if automatic
arrangement is off. It leaves the automatic-arrangement preference unchanged.

**Wall settings** groups the less frequent preferences:

- **Automatic arrangement:** when to arrange, whether other windows may resize,
  whether chosen sizes are remembered, and the toggle shortcut.
- **Dragging and previews:** Ctrl-drag, magnetic snapping, and resize ghosts.
- **Appearance:** discreet clickable lock icons.
- **Advanced** (collapsed): preserve visual order and the saved default algorithm.

The defaults enable automatic arrangement, resizing unlocked windows, remembering
chosen sizes, snapping, ghosts, and lock icons. Best fit is the default algorithm.

The illustrations below use simplified media windows. They show the behavior of
the controls; their positions are examples rather than exact packing results.

The algorithm can also be set to `Masonry` or `MaxRects`. The right-click menu's
`Packing algorithm (this session)` overrides the saved default without changing
it. Choose `Use settings` to return to the saved algorithm. Changing the session
algorithm repacks the current wall when automatic arrangement is enabled.

MaxRects packs rectangles without rotating the media. Best fit uses heuristics;
it does not guarantee a mathematically optimal arrangement. Older installations
without `rectpack` fall back to masonry; the normal requirements installation
includes the dependency.

Opening a new wall always chooses initial sizes from the media proportions.
Subsequent repacks use the current window shapes. The existing
`Floating resize keeps aspect ratio by default` setting and Shift override still
control manual resizing. Media itself retains its existing fit/zoom behavior.

For example, resize the first of ten windows and release the mouse: its chosen
size is kept while the others are arranged around it. Resize a second and third
window and their sizes are kept too. The windows may move during a repack.
Use **This window -> Keep size** to keep its dimensions, or **Flexible** to release
all its locks. **Reset layout -> Release kept sizes** releases size locks across the
wall. Use **Arrange now** to apply another layout.
Explicitly kept sizes remain respected even when automatic preservation of
manual resizes is disabled. Size choices last for the lifetime of each window.

![Three stages: begin with a wall, resize landscape window A, then release the mouse. A keeps its enlarged size while the other windows may move or resize, retaining their proportions.](../images/guides/wall-resize-reflow.png)

*The amber outline marks the window you resize. The lock marks its kept size.*

With automatic sizing off, packing only changes positions. It cannot increase
the windows' combined area. If the sizes do not fit, the current geometry is left
in place and a temporary tooltip explains how to enable sizing or release kept
sizes. The message does not add a status-bar row or reduce the viewer area.

![Automatic sizing comparison: when on, unkept windows may move and resize; when off, all current window sizes stay fixed and only positions change. Kept window A is the same size in both examples.](../images/guides/wall-sizing-options.png)

*Automatic sizing applies to windows without kept sizes. Both modes preserve
window proportions; fixed sizes cannot always be made to fit.*

**Keep the current visual order** in Wall settings -> Advanced uses the existing saved rearrange-order
preference. It keeps the current top-to-bottom, left-to-right order, which can
leave less room for packing. Disable it to allow more rearrangement.

## Manual Control

![Manual controls: hold Alt to bypass one gesture or turn off automatic resize arrangement with Ctrl+Alt+M.](../images/guides/wall-manual-controls.png)

- Hold **Alt** during a resize to skip automatic reflow for that gesture. Releasing
  Alt before the mouse still skips that gesture's reflow. Its new size is remembered.
- Alt-drag also suppresses the floating-window compare-merge gesture.
- Toggle **Arrange automatically after resizing** with **Ctrl+Alt+M**, or from the
  Wall layout menu, to make several manual adjustments. This choice is saved.
- Resuming automatic layout takes effect on the next resize; it does not immediately
  rearrange the wall. **Arrange now** explicitly arranges even when automatic arrangement is off.
- Automatic reflow preserves playback, synchronization, wall controls, and the
  viewer's fit/custom-zoom state. A new gesture, setting change, close, or automatic-arrangement
  toggle cancels an older pending layout result.

Layout calculations for resize reflow run in a worker using only geometry. They
do not reload media or restart the wall. Initial opening and the explicit
`Arrange as Masonry Wall` command retain their synchronous layout calculation.

## Review Badges

Review badges are item-level marks stored separately from normal tags.

They are meant for review workflow state, not caption content. A badge can mean whatever you want it to mean in your workflow.

Current default badge set:

- `1 2 3 4 5`
- `*`
- `!`
- `?`
- `X`

All symbolic badges are stackable. Numeric badges act like a single rank slot.

## Add Badges In The Wall

- Hover a masonry wall viewer to reveal the 3x3 badge slots.
- Click a slot to add or remove that badge from that file.
- After hover leaves, active badges stay visible on that viewer.
- Hover a badge slot to see the generic tooltip.

This makes the wall usable as a direct review surface instead of only a comparison layout.

## Review Toolbar

The detachable `Review toolbar` gives you the same badge actions outside the wall overlay.

- Click badge buttons to add or remove review marks.
- Use `Clear -> Clear Selected` to clear badges from the current review target.
- Use `Clear -> Clear Current Folder` to clear all review badges in the loaded folder.

`Clear Current Folder` shows a confirmation dialog before it runs.

## Position anchors and magnetic dragging

Hold **Ctrl** before pressing the left mouse button on a wall window, then drag.
The window moves while translucent rectangles preview where the other windows
will fit. The real sibling windows stay still until you release the mouse.
Dark red borders identify the dragged window and existing anchors during the gesture.
Release to apply the preview and anchor this window. The borders disappear and a
tiny translucent pin outline remains. A dotted anchor outline indicates a kept size. Repeat with another window to compose around multiple anchors.

- Screen edges and other anchors attract the dragged window within 10 logical pixels.
  Snapping respects the wall gap and releases beyond 18 pixels to avoid jitter.
- Hold **Shift** during Ctrl-drag for precise placement without snapping.
- Press **Escape** to cancel and restore the starting position.
- A red ghost preview means no layout fits. Releasing restores the dragged window
  to its starting position, retains existing anchors, and shows a temporary tooltip.
- Right-click a window, open **Wall layout**, and choose **This window -> Flexible**
  to release all its locks, or **Keep size** to allow movement only.
  **Reset layout -> Unpin all windows** releases all visible wall pins.
- **Ctrl-drag to pin a window** and **Snap to screen edges and other pins** are
  under **Wall settings -> Dragging and previews**.

Anchors keep both position and size during repacking, including resize-driven reflow.
They are separate from kept sizes: resetting kept sizes does not unpin windows.
You can still deliberately resize or move an anchor; its new geometry becomes its
constraint. Ordinary dragging and Alt-drag retain manual behavior. Explicit Ctrl-drag
works even when automatic arrangement is off. Anchors last for the lifetime of the window.

During Ctrl-drag, anchored packing preserves orientation and favors nearby placements
at the current sizes, shrinking unkept windows only when necessary and automatic sizing
is enabled. After a normal resize or explicit repack, unkept windows can grow again
to fill available space. Anchors retain their geometry, including any deliberate resize.
It uses an obstacle-aware rectangle planner regardless of the initial wall algorithm;
anchors take precedence over screen-order and alignment preferences. The dragged
window stays on its starting screen during the gesture.

## Badge Settings

`Settings -> Badges` lets you customize the current badge system without changing the number of slots.

You can change:

- badge symbol/label
- optional hover title
- badge color
- shortcut mapping
- text color
- font size
- corner roundness

These settings apply live across:

- the review toolbar
- the masonry wall overlay
- image-list badges

## Keyboard Shortcuts

Default review shortcuts:

- `1` to `5` for numeric rank badges
- `8` or `Shift` + `8` for `*`
- `?` for question
- `X` for reject
- apostrophe/quote key for warning

The exact mappings may differ if you customized them in `Settings -> Badges`.

## Image List Behavior

- Review badges also appear on thumbnails in the image list.
- They persist across reloads because they are saved in the folder DB and JSON sidecars.
- Filtering can use review predicates such as `review:true`, `review:reject`, `review:idea`, and `review_rank:>=2`.

## Related Docs

- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Compare Guide](COMPARE_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Shortcuts](SHORTCUTS.md)

The illustrations have editable SVG sources beside their PNG exports in
`images/guides/`. Rebuild them with
`venv/Scripts/python.exe scripts/render_wall_guide_illustrations.py`.


## Size locks, anchors, and resize previews

- **This window -> Keep size** fixes dimensions but lets packing move the window.
  With **Remember sizes I change** enabled, a manual resize creates this constraint automatically.
- **This window -> Pin in place** fixes both dimensions and placement during packing.
  Ctrl-drag creates this constraint; you can still deliberately resize the anchor.
- Turn off **Arrange automatically after resizing** to suspend resize reflow; Alt bypasses it for one gesture.

Resize ghosts show the proposed release layout without moving the other windows.
The amber outline is the resized window's proposed destination, which can differ
from its current position if it is not anchored. Blue outlines show the other windows.
A red preview indicates that no layout fits. Disable **Show ghosts while resizing**
in Wall settings -> Dragging and previews if desired. Reflow settings and size constraints still apply.

The narrow outer resize border takes priority over video-control buttons; controls
remain clickable inside that border. This includes the floating player panel and
hover playback buttons.

Constraint icons sit in the bottom-left corner, inset beyond the resize border,
without a solid background. Hover to brighten an icon; click it to release only
that constraint on that window. The pin
means anchored position; the dotted anchor means kept size. A pinned window shows only the pin. Clicking it reveals a size lock if a separate
kept size remains. Turn off **Wall settings -> Appearance -> Show lock icons** to hide
them without changing the constraints.

An anchor may extend off-screen after a deliberate resize. Reflow preserves that
geometry and packs unanchored windows into the remaining visible space, respecting
kept sizes and minimum window sizes. The unanchored windows must remain on-screen.

Hint creation is disabled in floating viewers, including comparison viewers.
Ctrl-drag remains available for wall positioning without entering hint insertion.
Create hints in the main viewer; existing hints still display in floating viewers.
