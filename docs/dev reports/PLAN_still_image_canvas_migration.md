# Still Image Canvas Migration Plan

## Why this exists

TagGUI's current viewer path is a mixed architecture:

- still images
- video playback
- markings
- compare overlays
- tagging workflow interactions

That shared path is productive, but it is not the best long-term fit for "serious image viewer" behavior. The recent panning fix improved the immediate issue, but it did so by optimizing around the current `QGraphicsView` stack rather than replacing the root cause.

The long-term direction should be:

- dedicated still-image renderer/canvas
- separate video renderer
- shared overlay and interaction model on top

This is closer to the architectural advantage seen in ImageGlass, without copying its Windows-specific implementation directly.

## Decision

If time and implementation cost are acceptable, TagGUI should migrate away from the current still-image viewer architecture as the final design.

It should **not** directly transplant ImageGlass internals.

Instead, TagGUI should adopt the same core idea:

- a dedicated still-image canvas for pan/zoom/render quality
- a separate media/video path
- higher-level tools layered above both

## Goals

- Make still-image pan/zoom behavior first-class.
- Remove accidental coupling between image viewing and video backend selection.
- Preserve TagGUI-specific features:
  - markings
  - crop workflows
  - compare overlays
  - spawned viewers
  - zoom-follow behavior where it still makes sense
- Keep migration incremental and reversible.

## Non-goals

- Do not rewrite the video system in the first pass.
- Do not replace every `QGraphicsView` use immediately.
- Do not copy ImageGlass's Direct2D/WinForms code directly.
- Do not break Linux support by choosing a Windows-only rendering design.

## Current pain points

- Image rendering quality/performance is coupled to a viewer path that also serves video and graphics overlays.
- Viewer behavior can change based on video backend selection.
- High-resolution panning exposes limitations in the current Qt scene/view path.
- The architecture favors interaction convenience over still-image rendering quality.

## Proposed target architecture

### 1. Still image canvas

Introduce a dedicated `StillImageCanvas` widget responsible for:

- image loading/display state
- zoom and fit math
- panning state
- interpolation choice
- viewport-to-image coordinate mapping
- efficient redraw of a single image surface

This widget should own:

- current image source
- transform state
- visible rect / source rect / destination rect
- fast-pan vs high-quality display policy

This widget should not own:

- tagging logic
- viewer orchestration
- video playback
- app-level compare state

### 2. Overlay adapter layer

Markings, crop rectangles, compare dividers, and similar tools should be rendered as overlays using a shared abstraction instead of directly depending on `QGraphicsItem`.

That abstraction should provide:

- image-space to view-space mapping
- hit testing
- overlay draw calls
- cursor and drag handling

### 3. Viewer coordinator

`ImageViewer` remains the orchestrator, but it chooses one of two rendering paths:

- `StillImageCanvas` for static images
- current video path for videos

This keeps the higher-level UI stable while changing the still-image engine underneath.

## Migration strategy

### Phase 0: Stabilize current bridge

Keep the current shipped fixes:

- do not force `mpv_experimental` into the non-GL image viewport path
- use full viewport updates on the GL path
- use fast transform/caching while actively panning still images
- prefer desktop OpenGL hints on Windows

This gives immediate value while the larger work is evaluated.

### Phase 1: Extract viewer math and state

Before introducing a new canvas, move core image-view state out of `QGraphicsView` assumptions:

- zoom factor
- fit mode
- pan center / visible region
- image-to-view coordinate conversion
- compare split ratios

Deliverable:

- a reusable image viewport state object that is independent of scene items

This is the most important step for reducing migration risk.

### Phase 2: Introduce `StillImageCanvas` in parallel

Add a new widget behind a feature flag or local runtime toggle that can:

- load a static image
- fit to viewport
- zoom at cursor
- pan smoothly
- expose image/view coordinate conversion

At this phase, do **not** port markings yet.

Deliverable:

- a basic still-image viewer path that can be visually compared against the old one

### Phase 3: Port overlay rendering primitives

Port the minimum overlay set:

- crop rectangle
- include/exclude/hint rectangles
- hover handles
- label anchors if needed

The overlay system should be implemented against the new canvas API, not against Qt graphics items.

Deliverable:

- feature parity for core marking workflows on still images

### Phase 4: Port interaction behavior

Move these behaviors onto the new canvas:

- drag-to-pan
- wheel zoom
- double-click zoom behavior
- cursor feedback
- selection / resize hit testing
- keyboard pan helpers

Deliverable:

- daily-use still-image workflow parity

### Phase 5: Compare mode migration

Compare mode should be handled separately because it adds complexity quickly.

Recommended order:

1. single overlay compare
2. split divider
3. multi-layer compare if still needed in the same form

Deliverable:

- compare mode parity without reintroducing scene/view coupling

### Phase 6: Spawned viewers and synchronization

After still-image parity exists for one viewer, port:

- spawned viewer behavior
- pan/zoom synchronization
- compare sync where needed

Deliverable:

- multi-view workflows continue to work with the new canvas

### Phase 7: Remove old still-image dependency path

Only remove the old still-image `QGraphicsView` path after:

- static image navigation is clearly better
- marking parity is acceptable
- compare mode is stable
- spawned viewers are stable

Video can continue using its current path until a separate decision is made.

## What should stay on the old path at first

These should **not** be migrated in the first wave:

- MPV/VLC playback path
- reverse video playback path
- video controls skinning behavior
- video sync coordinator internals

This plan is about still-image rendering first.

## Main risks

- overlay hit testing becomes harder once `QGraphicsItem` is removed
- compare mode can balloon the scope quickly
- coordinate bugs will appear if state extraction is incomplete
- duplicated behavior may exist temporarily while both paths coexist

## Risk controls

- keep old and new still-image paths available during migration
- extract math/state before drawing code
- ship in phases with feature parity checkpoints
- avoid touching video architecture until still-image work is proven

## Exit criteria

Proceed with the larger migration only if the new canvas delivers:

- clearly smoother still-image panning and zooming
- no coupling to video backend choice
- acceptable marking/crop parity
- no major regression in compare/spawned viewer workflows

If those criteria are not met, keep the current architecture plus tactical optimizations.

## Recommendation

Short term:

- keep the current fixes
- do not refactor immediately under urgency

Long term:

- migrate to a dedicated still-image canvas architecture
- keep video separate
- port TagGUI's value-added features consciously instead of trying to preserve the old shared scene model at all costs
