# Known Limitations

Current known constraints in TagGUI Video 1M.

## Filtering and Metadata

- Tags and star ratings have DB-backed support in the current large-folder path.
- Markings are still stored in sidecar JSON metadata.
- Marking-related filters such as `marking:`, `crops:`, and `visible:` are not yet fully implemented in the DB-backed paginated SQL path.

## Video Captioning

- Current video captioning support is frame-based.
- TagGUI can caption or tag the current frame or cropped frame region.
- It does not yet perform full-video timeline-aware captioning across an entire clip.

## Video and Playback

- Backend behavior can differ.
- The project currently prefers the MPV path, but backend-specific behavior still needs clearer dedicated documentation.

## Skin Designer

- The skin system works, but the skin designer is still experimental.
- Designer parity, polish, and edge-case behavior still need work.

## Large-Folder UX

- First-open behavior on very large folders can still involve noticeable scanning, DB build, or thumbnail work before the folder settles into a faster cached path.
