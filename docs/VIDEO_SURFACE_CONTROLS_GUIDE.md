# Video Surface Controls Guide

[Back to Documentation Hub](HUB.md)

This guide covers the contextual video controls that appear directly on the viewer surface when the normal video control bar is hidden.

These interactions work in the main viewer and in spawned viewers.

## When They Appear

The contextual controls are meant to replace the most important playback actions when the normal video controls are not currently visible.

- If the normal video controls are visible, the contextual surface controls stay hidden.
- If the normal video controls auto-hide or are fully off, the contextual surface controls can appear again on hover.
- Spawned viewers do not keep video controls permanently visible; they use auto-hide or off behavior.

## Left and Right Seek Zones

Hover near the lower left or lower right side of the video to reveal the contextual seek icon for that side.

- Single click starts a seek burst.
- Repeated clicks on the same side accumulate a larger pending seek.
- Double click also extends that same burst.
- Click and hold keeps accumulating while held.
- When you stop clicking or holding, the viewer commits one combined seek.
- Mouse wheel over either side zone also seeks.
- Wheel direction decides forward or backward seek.
- Wheel seeking briefly shows scrub feedback so you can see where you are landing.

The current seek burst ramps like this:

- `1s`
- `2s`
- `5s`
- `10s`
- then `+10s` for each further step

## Bottom Scrub Zone

Hover the lower center area of the video to use the contextual scrub bar.

- Click and release seeks directly to the clicked position.
- Click and drag scrubs along the timeline.
- Double click toggles play and pause.
- Click and hold enters temporary speed mode instead of seeking immediately.

## Temporary Speed Mode

Holding on the contextual scrub bar enters the green temporary speed mode.

- It starts at a temporary review speed.
- Moving left or right while still holding changes the temporary playback speed.
- Releasing returns playback speed to the previous value.

The contextual scrub overlay turns green while this mode is active, and the normal control bar also reflects that state when it is shown.

## Notes

- The contextual controls are intentionally separate from the normal player skin and control-bar buttons.
- The scrub-bar double-click play/pause action shares space with the immediate single-click seek behavior, so the first click of a very fast double click may still reposition the timeline slightly before playback toggles.
- Reverse playback and other backend-specific video behavior still depend on the active video backend.

## Related Docs

- [Video Workflow Guide](VIDEO_WORKFLOW_GUIDE.md)
- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Shortcuts](SHORTCUTS.md)
- [Video Backends](VIDEO_BACKENDS.md)
