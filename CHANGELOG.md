# Changelog

All notable changes to TagGUI Video 1M are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-04-10

### Added

- Add Gemma 4 local captioning and model unload controls
- Add support for the Gemma 4 multimodal model family in auto-captioning
- Enable Gemma image and native video captioning from the model picker
- Let Max video frames use 0 as automatic backend-controlled sampling
- Add a compact unload control beside the model selector for switching local models
## [1.0.55] - 2026-04-09

### Added

- Clicking an image now rereads its sidecar without resetting the masonry layout
- External caption edits still appear when the image is selected
- Passive sidecar sync no longer causes paginated page reload churn

### Fixed

- Fix masonry churn when sidecar tags resync on click
## [1.0.54] - 2026-04-09

### Added

- Polish All Tags panel and captioning workspace defaults
- Add Ctrl+wheel zooming for the All Tags list while keeping the count column readable
- Refine the contextual clear-filter action so it takes less panel space
- Make the Auto Captioning workspace open with a more balanced split between Image Tags and Auto-Captioner

### Fixed

- Fix repeated sort selection so it toggles ascending and descending correctly
## [1.0.53] - 2026-04-09

### Added

- Refine captioning and tag panel UX
- Add a more compact All Tags panel layout with cleaner controls and count display
- Add Ctrl+wheel zooming for the All Tags list so text can be resized live
- Show filtered versus total tag counts only when they differ
- Make Clear Image List Filter contextual instead of always taking panel space

### Fixed

- Improve startup crash logging so failures are easier to diagnose
- Fix app shutdown so the window and terminal close cleanly after saving layout and selection
## [1.0.52] - 2026-04-09

### Added

- Add a cleaner compact auto-captioner layout while keeping the classic layout available
- Add reset defaults for advanced caption generation settings
- Make toolbar toggles easier to use from the View menu without it closing after every click
- Clean up Auto-Captioner and Toolbars menu organization

### Changed

- Improve auto-captioner compact mode and view menu organization
- Improve compact panel spacing, resizing, prompt editing, and advanced settings usability
## [1.0.51] - 2026-04-08

### Added

- Long descriptive entries now render on a single line instead of expanding the row height
- Tag editing, filtering, and counts continue to use the original tag value

### Fixed

- Fix oversized rows in the All Tags panel
## [1.0.50] - 2026-04-08

### Added

- UI: Added 'huihui-ai/Huihui-Qwen3.5-9B-abliterated' to the model suggestion dropdown.

### Changed

- FEATURE: Added 'Disable reasoning' checkbox for Qwen models (enabled by default) for 2-5x faster captioning.
## [1.0.49] - 2026-04-06

### Added

- DEPS: Updated and pinned stable dependency stack (Transformers 5.5, bitsandbytes 0.49, qwen-vl-utils 0.0.14).

### Fixed

- FIX: Resolved 'AttributeError' in Video Player when switching videos during active auto-captioning.
- FIX: Patched Qwen-VL image captioning to handle strict 'fps' validation in newer transformers versions.
## [1.0.48] - 2026-04-06

### Added

- Enable Native Video Captioning through Qwen3.5-VL
- Integrated full support for Qwen2.5-VL and Qwen3.5-VL models
- Added native video understanding that analyzes multiple frames across duration
- New System Prompt field in the Auto-Captioner sidebar for granular control
- Automatic Reasoning Stripping: Internal thoughts are now cleanly removed from metadata
- Advanced settings now support beams, repetition penalty, and length penalty

### Fixed

- Increased default Max output tokens and added explicit error on truncation
## [1.0.47] - 2026-04-05

### Added

- Remote API Improvements and Workspace Adjustments
- Improved the Remote API 'Endpoint' field by converting it into a dropdown with sane, pre-verified OpenAI-compatible suggestions (LM Studio, Ollama, Google AI, Groq, etc)
- The Remote API endpoint and model name fields now remember their history
- Updated the 'Auto Captioning' workspace layout specifically so that 'Image Tags' and 'Auto Captioner' panels sit on top of each other (split vertically) instead of behind tabs, allowing them to be used at the same time
## [1.0.46] - 2026-04-05

### Added

- Obfuscate API Key in UI
- The API Key field in the Remote model settings now masks input to prevent exposing credentials during screencasts or screen sharing
## [1.0.45] - 2026-04-04

### Added

- The default Remote API model name suggestion is now 'gemini-3-flash-preview', which has been confirmed to work well with the current Google Gemini endpoint

### Changed

- Update default Remote API model
## [1.0.44] - 2026-04-04

### Added

- Add Max output tokens control for Remote API captioning
- New 'Max output tokens' field appears in the Remote model settings panel
- Default is 8192 (enough for detailed captions without truncating)
- Adjustable from 100 to 200,000 to accommodate different API providers
- Improved default prompt to discourage verbose markdown output from models like Gemini
## [1.0.43] - 2026-04-04

### Added

- Add OpenAI-compatible remote API captioning
- Use any OpenAI-compatible vision API for captions (local or cloud)
- Works with LM Studio, Ollama, OpenAI, Google Gemini, Groq, etc.
- Configure endpoint URL, API key, and model name directly in the Auto-Captioner panel
- Remote settings (endpoint, key, model name) shown only when Remote is selected
- Irrelevant local settings (Device, 4-bit, Advanced) hidden for Remote mode
- Errors are shown in the console and never written as captions to images
- Safety-blocked or empty responses are skipped cleanly with a console message
## [1.0.42] - 2026-04-03

### Changed

- Improve Python 3.13 installation reliability
- Improve compatibility with newer Python environments

### Fixed

- Fix Windows installs failing while setting up sentencepiece
## [1.0.41] - 2026-04-03

### Added

- Add shortcut-based tag filter composition
- Click a tag in All Tags to replace the current image filter
- Ctrl/Cmd+click a tag to add it with AND
- Alt+click a tag to add it with OR
- Filtering and shortcuts docs now describe the new behavior
## [1.0.40] - 2026-04-03

### Added

- Opening a paginated folder now repairs loaded items first and continues small background sync work without full rescans
- Clicking an item or running bulk tag operations now refreshes stale DB tag rows more reliably

### Changed

- Improve sidecar tag sync reliability

### Fixed

- Fix cases where All Tags, tag filters, and search/replace could show stale tag values after sidecar edits
## [1.0.39] - 2026-04-02

### Added

- Different random seeds now produce different image orders in DB-backed paginated views
- Reusing a saved random seed now restores the expected order instead of silently reusing the same list
- Old cached random-order ranks are rebuilt automatically under the corrected logic

### Fixed

- Fix random sort seed replay in paginated folders
## [1.0.38] - 2026-04-02

### Added

- Cold-cache paginated folders recover masonry layouts more reliably after fresh loads
- Random sort now shows its active seed directly in the dropdown
- Right-click the Random sort control to copy, reuse, or enter a seed and restore a prior order
- Saved folder view preferences now keep the random seed with the Random sort mode

### Changed

- Improve masonry recovery and random sort replay
## [1.0.37] - 2026-04-02

### Added

- Keep masonry updating correctly as large thumbnails arrive instead of leaving random items stuck with placeholder sizing

### Changed

- Improve masonry recovery after clearing cache
- Improve cold-cache behavior on small folders where dimensions and thumbnails load progressively

### Fixed

- Fix paginated folders that could reopen with stale placeholder dimensions after a cache clear
## [1.0.36] - 2026-03-27

### Added

- Keep real image dimensions after sorting paginated results by Created
- Prevent masonry from falling back to placeholder aspect ratios after reloads

### Fixed

- Fix masonry placeholders returning after sort
- Fix the click crash triggered by virtual-list selection handling
## [1.0.35] - 2026-03-24

### Added

- Reduce masonry surprise recentering and clean up the top menu strip
- Clicking a visible masonry item after closing a spawned viewer no longer recenters the viewport unexpectedly
- The title bar now shows subfolder context for the selected media item
- The top menu strip should stay visually closer to its previous height

### Removed

- The red delete-marked button is back next to the menu items instead of appearing after the reaction controls on the far right
## [1.0.34] - 2026-03-24

### Added

- Reduce stale masonry recentering and show subfolder context in the title bar
- Clicking another visible masonry item after closing a spawned viewer no longer recenters the viewport unexpectedly
- The title bar now shows the selected file inside its collection subfolders, not just the root folder and filename
- It is easier to tell which nested set or collection a media item belongs to while browsing
## [1.0.33] - 2026-03-24

### Added

- Clean up image list controls and reduce masonry viewport jumps
- Simplify the image list header with a cleaner single-row layout and media scope tabs
- Keep reactions available on the menu row or on the main viewer overlay without the finicky detach behavior
- Clicking a partially visible masonry tile no longer forces the viewport to move just to fully reveal it
- Next and previous style navigation still reveals items when needed

### Removed

- Remove the old selection toggle from the image list controls
## [1.0.32] - 2026-03-23

### Added

- Clean up the image-list header
- Put filter, sort, and media scope on one cleaner header row
- Replace the media filter dropdown with clearer All, Images, and Videos tabs
- Use a more discreet tab style so the panel draws less attention

### Removed

- Remove the confusing selection toggle from the Images panel
## [1.0.31] - 2026-03-23

### Added

- Jumped items now stay anchored more consistently while nearby pages load and enrich
- Startup restore lands more smoothly and avoids long UI freezes
- Page dragging, typed jumps, and sort restores behave more predictably
- Splitter snapping works again after using the thumbnail zoom buttons

### Changed

- Improve deep jumps and masonry stability
- Deep page and startup jumps are much faster and more reliable on very large datasets
## [1.0.30] - 2026-03-21

### Added

- Love, bomb, and star state now survive DB rebuilds through sidecar metadata
- Love / Rate / Bomb sorting is more reliable after folder reloads and masonry repair
- Keyboard and control-based media navigation stay in sync with reaction state
- Scrub-zone play/pause uses the same persistent toggle as the main player controls

### Changed

- Improve curator resilience and navigation stability
## [1.0.29] - 2026-03-21

### Added

- Add contextual left and right seek zones with hover, click, hold, and wheel interactions
- Add a bottom scrub overlay for direct seek, drag scrubbing, and temporary speed control
- Keep contextual controls hidden while the normal video controls are visible

### Changed

- Improve video seeking and scrubbing interactions
- Improve consistency between contextual seek actions and the video control bar

### Fixed

- Fix overlay visibility during reverse playback and improve spawned viewer control behavior
## [1.0.28] - 2026-03-21

### Added

- Main viewer video controls now support always shown, auto-hide, or always hidden modes
- Videos now support left/right seek zones with hover feedback and accumulated click-to-seek behavior

### Changed

- Improve video controls and masonry interaction polish
- Masonry thumbnail zooming behaves more consistently and keeps the selected item centered better
## [1.0.27] - 2026-03-20

### Added

- Screenshot current video frames now appear almost instantly
- Duplicates sort more like newly created files in recent-first views

### Changed

- Duplicate media now shows up much faster in the current folder

### Removed

- Speed up duplicate, screenshot, and delete workflows
- Delete selected and Delete Marked now remove items without a full folder refresh
## [1.0.26] - 2026-03-20

### Added

- Page jumps, exact image jumps, and Home/End navigation are more stable in full masonry mode
- Double-click now spawns a floating viewer by default, with a setting to switch back to the system default app
- Auto-spawned viewers stay inside the current monitor on double-click, while drag-spawn still respects the release position
- Reaction feedback now appears reliably on video thumbnails in full masonry when the main viewer is hidden
- Batch rating and mixed reaction states are handled more cleanly

### Changed

- Improve masonry jumps, spawned viewers, and reaction feedback
- Opening media in the system default app behaves better on Windows
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
