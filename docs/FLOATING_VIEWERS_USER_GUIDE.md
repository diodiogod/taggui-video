# Floating Viewers User Guide

[Back to Documentation Hub](HUB.md)

This guide covers spawned/floating viewers (PiP-style windows): how to open them, move/resize them, and use the new smart zoom behaviors.

## What They Are

- The main viewer stays anchored in the app.
- Floating viewers are extra media windows you can spawn and place anywhere.
- You can open multiple floating viewers at the same time.
- Each floating viewer keeps its own currently loaded media.

## Spawn Floating Viewers

- View menu: `View -> Spawn Floating Viewer`
- Shortcut: `Ctrl+Shift+N`
- Close all shortcut: `Ctrl+Shift+W`
- Hold existing spawned viewers: `H`
- Right-click in the main viewer area and spawn.
- Drag a thumbnail from list/masonry and release on empty screen area to spawn at drop location.

## Move, Resize, Close

- Move window with `middle-click + drag` anywhere inside a floating viewer.
- If media is fully fit and not pannable, `left-drag` moves the floating window.
- If media is zoomed/pannable, `left-drag` pans media instead; use white edge handles or middle-drag to move window.
- Resize from all corners and all borders (drag edge/corner zones).
- Close button (`x`) appears on hover near the top-right corner.

## Hold Mode

- `H` toggles hold mode for existing spawned viewers.
- Middle-click in the main window or image list area also toggles hold mode.
- In hold mode, existing spawned viewers become dimmed, gray, and click-through.
- Hold mode is meant to keep spawned viewers visible but out of the way while you keep working in the main app or spawn new viewers.
- Turning hold mode off restores normal interactivity.

<p align="center">
  <img src="../images/floating-viewers-spawn-move-hold.gif" alt="Floating viewers spawn move and hold workflow" width="74%">
</p>

## Mouse and Zoom Behavior

- Mouse wheel zooms in/out as usual.
- Floating viewer left double-click has adaptive behavior:
1. If there are left/right bars, it zooms to fill width.
2. If there are top/bottom bars, it zooms to fill height.
3. If no bars and media is pannable, it zooms back out to fit; custom zoom is only remembered when you intentionally changed zoom (not from plain auto in/out).
4. If still unpannable/no-op, it restores the stored custom zoom (if available) when you double-click on media; otherwise it uses the configured detail jump zoom.
- Width/height fill zooms center around the clicked media area (autopan to click target).
- Detail jump zoom amount is configurable in `Settings -> Advanced -> Floating double-click detail zoom (%)` (applied live).
- Stored zoom memory is temporary and per floating viewer; it resets when that viewer loads a different file.
- Double-clicking in black-bar area resets to fit and clears the stored custom zoom.

## Right-Click Menu on Floating Viewers

- `Sync video`: aligns loaded videos to loop start (or frame 0) and starts them together.
- `Close all spawned viewers`: closes floating viewers and compare windows.
- `Exit compare mode`: appears only when that viewer is in image-compare mode.

## Compare Merge (A/B Slider)

- `image + image`: opens in-place compare mode in the target viewer.
- `video + video`: opens a dedicated A/B comparison window.
- Mixed media pairs (`image + video`) are rejected with blocked feedback.
- Video A/B compare auto-runs sync logic for the two compared videos (no sync button shown in that window).
- Hold time is fixed at about 1 second.
- The target's current media becomes the left side (A), and the dropped/merged media becomes the right side (B).
- The vertical divider follows mouse X while compare mode is active.

How to open compare mode:

- Drag a thumbnail from the image list onto a target viewer (main or floating), hold for ~1s, then release.
- Drag one floating window onto another target viewer, hold for ~1s, then release.

What happens on merge:

- If the source is a floating window, it closes after a successful merge into the target.
- If the target is already in compare mode, the new merge expands the compare first.
- Once the compare is already full, a new merge replaces the right-side layer.

How to exit compare mode:

- Press `Esc`.
- Or use `Exit compare mode` from the floating viewer context menu.

## Video Behavior Notes

- A spawned viewer can inherit speed and loop state from the source viewer when opening the same video.
- Speed is per viewer.
- Loop markers are persisted with viewer scopes (`main`, `floating_*`) so different viewers can keep different marker ranges for the same media.

## Related Docs

- [Compare Guide](COMPARE_GUIDE.md)
- [Video Workflow Guide](VIDEO_WORKFLOW_GUIDE.md)
- [Shortcuts](SHORTCUTS.md)
