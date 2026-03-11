# Changelog

All notable changes to TagGUI Video 1M are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.7] - 2026-03-11

### Added

- Add main-viewer fullscreen mode
- add fullscreen for images and videos in the main viewer with F to toggle and Esc to exit
- keep previous and next media controls available in the viewer overlay and fullscreen mode
- support mouse back and forward buttons for media navigation across the app
- document the new fullscreen workflow, shortcuts, and floating-viewer behavior
## [1.0.6] - 2026-03-11

### Added

- Reduce black-frame flashes when scrubbing paused videos, including zoomed views
- Make paused timeline scrubbing smoother even before a clip has been played once
- Prevent paused seek interactions from leaking stale frames across video switches

### Changed

- Improve paused video scrubbing and masonry thumbnail paint stability
- Improve first paint reliability in paginated masonry so thumbnails replace placeholders sooner
## [1.0.5] - 2026-03-11

### Added

- Add a hover controls strip for the main viewer
- Let the controls switch between main-viewer overlay and toolbar fallback

### Changed

- Improve main viewer controls layout
- Improve hover stability and behavior on high-DPI displays
## [1.0.4] - 2026-03-10

### Added

- Hold Shift while resizing a spawned viewer to keep its aspect ratio
- Floating viewer docs and shortcuts now mention the new resize modifier

### Changed

- Improve floating viewer resizing
## [1.0.3] - 2026-03-10

### Added

- Release 1.0.3
- Toolbar groups remain movable and user-driven
- Reset actions restore the default toolbar and window layout
- Default toolbar packing is cleaner, with rating controls aligned to the right
## [1.0.2] - 2026-03-10

### Added

- Find and replace now persists correctly for paginated folders
- Undo and redo restore paginated bulk tag edits more reliably
- Batch reorder actions now ask for confirmation before running

### Fixed

- Fix paginated bulk tag editing

### Removed

- Remove duplicate tags and remove empty tags now handle sidecar captions correctly
## [1.0.1] - 2026-03-09

### Added

- Refine README support layout
- Move the large Ko-fi support button to the Support section at the end of the README
- Keep the compact donation badge visible in the top badge row
- Publish this patch through the new automated TagGUI version bump workflow
## [1.0.0] - 2026-03-09

### Added

- Establish the first TagGUI Video 1M semantic-version baseline
- Add an automated version bump script that updates the changelog and README
- Expose TagGUI release metadata from a single canonical version module
