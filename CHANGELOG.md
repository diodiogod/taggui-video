# Changelog

All notable changes to TagGUI Video 1M are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.25] - 2026-03-19

### Added

- Refine reaction feedback and footer layout
- restore the bottom-left folder image count in the image list footer
- smooth the bomb burst timing, glow, and off-state readability
- make the love-off state animate as a visible crack through the heart

### Changed

- improve heart and bomb keyboard reaction overlays so feedback is clearer
## [1.0.24] - 2026-03-19

### Added

- The image list can now be resized much narrower without losing the media-type filter
- Masonry view can collapse down to single-column layouts more reliably
- Love, bomb, and star rating shortcuts now show on-screen feedback even when reaction controls are hidden
- Bomb feedback uses a restrained burst animation, while love and stars get softer visual confirmation
- When the main viewer is hidden, reaction feedback now appears on the current thumbnail instead

### Changed

- Improve narrow masonry layouts and reaction feedback
## [1.0.23] - 2026-03-19

### Added

- Harden crop persistence during image switches
- Cropped areas now stick more reliably when switching images and coming back
- Reduce stale Qt callback errors from late marking release events

### Fixed

- Fix a release-time crop save path that could fail during fast image changes
## [1.0.22] - 2026-03-18

### Added

- Add detachable reaction controls overlay
- Stars, love, and bomb can now live in a separate hover cluster on the main viewer
- The reaction cluster can be attached to the viewer or returned to the toolbar like the main controls
- Narrow windows now avoid overlay conflicts by revealing the hovered cluster instead of overlapping toolbars
## [1.0.21] - 2026-03-18

### Added

- Long recent-folder paths now stay easier to scan in the File menu
- The last folder stands out more clearly without breaking the path layout
- Hovered recent-folder rows are easier to read on dark themes

### Changed

- Improve recent folders menu readability
## [1.0.20] - 2026-03-18

### Added

- Reuse an existing Windows Explorer window for the same folder when revealing media
- Add Alt-drag to send the real file to other apps instead of spawning a floating viewer
- Add Alt-double-click to reveal media in Windows Explorer
- Automatically reinstall normal dependencies when requirements.txt changes
- Document the new launcher and shortcut behavior

### Changed

- Improve Explorer integration and launcher dependency refresh
## [1.0.19] - 2026-03-18

### Added

- Add reaction shortcuts and reaction filter gestures
- love and bomb can now be toggled with L and B when focus is not in a text field
- Ctrl+click on the love or bomb button now applies the matching filter like the star control

### Changed

- Update the rating and reaction tooltips to show the new shortcut and filter behavior
## [1.0.18] - 2026-03-18

### Added

- paginated folders can pick up newly discovered media without requiring a full reload

### Changed

- Improve paginated refresh and batch context actions

### Fixed

- right-clicking a selected thumbnail no longer collapses an existing multi-selection before batch actions
## [1.0.17] - 2026-03-12

### Added

- Refine compare drag reset timing
- Large cursor movement no longer resets compare loading while the target is still blue
- Reset behavior still applies after the target reaches the green ready state
- Compare drag feedback is more stable for thumbnails and floating viewers
## [1.0.16] - 2026-03-12

### Added

- Opening thumbnails now requires a left-button double-click
- Compare hover activation resets after large cursor movement
- Crop guides stay visible during resize and no longer render red triangle artifacts

### Changed

- Improve compare and marking stability

### Fixed

- Marker dragging is more responsive and avoids crash-prone state
## [1.0.15] - 2026-03-12

### Added

- Add thumbnail size minus/plus controls to the image-list footer
- Allow direct thumbnail size entry by clicking the px readout
- Footer thumbnail size changes no longer resize the image-list panel width

### Changed

- Improve image-list thumbnail size controls
- Thumbnail size changes now update masonry immediately without requiring scroll
- Selected-image landing cues and anchoring behave better during thumbnail size changes
## [1.0.14] - 2026-03-12

### Added

- Batch video captioning no longer reuses the first loaded video's frame for other selections
- Single selected videos still caption the frame currently shown in the viewer
- Batch captioning now uses each video's saved loop start when available, otherwise frame 0
- Saved crop regions continue to apply during video captioning

### Fixed

- Fix video captioning frame selection
## [1.0.13] - 2026-03-12

### Added

- Spawned viewers no longer stay black after hold/unhold
- Frozen floating viewers behave like passthrough overlays again
- The H shortcut works again for floating hold mode
- Hold mode keeps the familiar grayed-out visual without breaking spawned images

### Fixed

- Fix floating viewer hold mode regressions
## [1.0.12] - 2026-03-11

### Added

- Shift-resizing spawned viewers now keeps manual zoom focused on the same image detail while resizing the window
- Floating viewer corners now show a clearer animated aspect-lock cue when using Shift
- Masonry resize and splitter changes now guide the eye to the selected image's new position
- Small selected-image position changes in masonry now still get a visible tracking cue

### Changed

- Improve resize guidance and masonry tracking
## [1.0.11] - 2026-03-11

### Added

- Keep undo and redo support for these actions while avoiding unnecessary whole-model work
- Preserve the existing save behavior after the UI updates

### Changed

- Improve rating and reaction responsiveness
- Make heart, bomb, and star interactions update immediately in the viewer toolbar

### Removed

- Remove long pauses caused by reaction and rating changes blocking the UI thread
## [1.0.10] - 2026-03-11

### Added

- Reduce aliasing and shimmer when shrinking images in the main viewer
- Make zoomed-out images look closer to thumbnail quality
- Keep panning responsive by preserving the existing fast-pan fallback
- Avoid changing video rendering behavior

### Changed

- Improve zoomed-out still-image quality
## [1.0.9] - 2026-03-11

### Added

- keep a longer recent-folder history without making the File menu overly tall
- show recent folders in a compact scrollable list

### Changed

- Improve recent folders history

### Removed

- allow removing one recent folder at a time with Delete or the inline close button
- refine the recent-folder remove control styling
## [1.0.8] - 2026-03-11

### Added

- allow dragging folders from the file manager into the app to open them
- allow dragging supported image or video files into the app to open their folder and select the dropped file
- make external drops work across the main window, image list, and main viewer

### Removed

- Add drag-and-drop folder loading
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
