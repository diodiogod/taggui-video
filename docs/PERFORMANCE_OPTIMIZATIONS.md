# Performance Architecture and Verification

This document describes the performance work introduced after TagGUI Video 1M
1.4.2. It records the intended architectural boundaries, the measurements that
motivated them, and the checks needed before release. The chronological
[audit diary](PERFORMANCE_AUDIT_DIARY_2026-07-17.md) contains the full
investigation log.

## Goals

- Show the usable GUI without initializing features the user has not requested.
- Keep image-only workflows independent of video and machine-learning runtimes.
- Make cached large folders useful before full background validation completes.
- Reduce CPU, allocation, and filesystem work in masonry and thumbnail hot paths.
- Preserve existing behavior by moving work to established feature boundaries
  rather than removing it.

## Measured Results

Measurements were taken on the audit machine with the same working tree and
represent development benchmarks rather than release guarantees.

| Scenario | Earlier measurement | Optimized measurement |
| --- | ---: | ---: |
| Clean `main_window` import | about 14.0 s | about 0.72–0.75 s |
| Import + application + unshown main window | about 4.45 s | about 0.70–0.87 s warm |
| Masonry layout, 250,000 items | about 590–624 ms | about 256–301 ms |
| Thumbnail cache paths, 20,000 reads | about 3.45 s | about 54 ms |
| Reopening an unchanged skin catalog | about 75 ms | about 0.6–0.7 ms |
| First deferred video-component construction | roughly 300+ ms | about 212–217 ms |

The 1,000,055-row indexed-folder test returned from `load_directory` with page
zero usable in about 712 ms while later pages warmed through the existing
executor. Fetching every path up front had taken about 3.12 seconds and about
168 MiB of peak Python memory.

## Startup Boundaries

Normal startup now keeps these feature families behind their first real use:

- Torch, Transformers, Ultralytics, caption-model adapters, and execution workers
- MPV and VLC probing, Qt Multimedia widgets, skin catalogs, and video editing
- OpenCV exact-frame fallbacks and deep video validation
- Settings, Export, Find/Replace, Batch Reorder, history, and confirmation dialogs
- comparison, fullscreen, and secondary-browser windows
- EXIF and image-size enrichment, changed-subtree process pools, grammar tools,
  and spell dictionaries

Model lists and availability metadata remain lightweight. Concrete model classes
resolve when captioning starts. Type-only worker references use
`TYPE_CHECKING`, preventing the lazy boundary from recreating circular imports.

Auto-Markings discovers model filenames when its selector is first opened and
does not construct an Ultralytics or ONNX Runtime session while restoring the
saved selection. A session is created when the user explicitly activates a
model or starts marking, and a matching prepared session is reused by Start.

The main image viewer creates its video player, controls, overlays, and media
objects on the first video. A first video can therefore have a small one-time
construction cost. Subsequent video switches reuse those components; decoding a
high-resolution video can still take longer than displaying its already-decoded
thumbnail or an image.

## Large Folders

For a valid paginated index:

1. The database count establishes the model size without loading every path.
2. Page zero becomes available synchronously.
3. The next pages warm through the existing page executor.
4. Delayed validation first compares the directory signature.
5. Only a changed directory performs full path reconciliation.

Fresh scans and non-paginated behavior are unchanged. Changed-folder validation
still preserves duplicate winner/removal behavior while using a single canonical
path map to reduce temporary memory.

## Masonry and Thumbnails

The masonry worker replaces repeated lambda scans and a second result-conversion
pass with tie-compatible loops that emit the final dictionaries directly.
Invalid aspect-ratio, spacing, ordering, and spacer semantics remain covered.

Thumbnail reads no longer create hash-bucket directories; writes create them as
needed. GUI probes test cache-file existence without decoding every pixmap, and
the preliminary preload scan stops once its decision threshold is known.
Completed tasks normally assign by the unchanged submitted row in constant time,
with a path search retained after sorting or reordering.

Completion callbacks are registered only after the future is stored. A callback
removes a future only if it is still the current future for that row, protecting
both very fast cache hits and replacement tasks.

## Intentional Tradeoffs

- The first use of a deferred feature pays its import or construction cost.
- The first video remains limited by backend initialization, media probing,
  decoder startup, keyframe placement, and file/device throughput.
- Hugging Face cache discovery runs when the Auto-Captioner model selector is
  first opened, rather than during startup. It remains on the UI thread because
  its helpers and combo-box updates share mutable state.
- The compact Auto-Captioner stylesheet remains synchronous to avoid an
  unstyled flash and layout-mode race.
- Entry-point media-runtime discovery and Pillow codec registration remain eager
  because saved-folder restoration may need their DLLs and decoders immediately.

## Release Verification

Before merging, manually verify:

- cold start with no restored folder;
- restore a small image folder and a large indexed folder;
- scroll while thumbnails are loading, then sort/filter during thumbnail work;
- open the masonry view and resize or change its column count;
- open the first video, play/pause/seek, then switch repeatedly between videos;
- repeat the video test with the configured Qt, MPV, and VLC backends that are
  supported by the release environment;
- run one local caption model, one remote caption model, auto-marking, and a
  pipeline;
- open Settings, Export, Find/Replace, Batch Reorder, Compare, fullscreen, and
  the secondary browser;
- enable spell and grammar checks and confirm model availability indicators;
- reopen the video-skin menu, then edit a skin and confirm cache invalidation.

The final audit suite reached 92 passing tests with nine failures also present in
untouched baseline areas: compare dragging, masonry submission cadence, sidecar
reconciliation, and strict scroll-domain expectations. Compare these failures
against the target branch before treating them as regressions.

## Further Optimization

Broad startup optimization now has diminishing returns. Future work should be
profile-driven and preferably isolated by subsystem.
