# Masonry/navigation audit — 2026-09-20

Baseline: `d543529` (the user-approved bidirectional loading and jump fixes).
The changes below are deliberately uncommitted until tested in the real GUI.

## Changes

- Cancel obsolete running page materialization between file reads, not just
  queued futures. Preserve useful running neighbors, reject partial results,
  and keep an older worker's cleanup from clearing a replacement request.
- Prepare normalized image path keys in page workers. Reuse them for dimension
  repair and selection lookup; invalidate on path/folder changes. Remove the
  ambiguous basename match that could select an image in another subfolder.
- Bind repair reads, queued dimensions, and completion delivery to their
  original dataset. Sort/filter resets invalidate both running repairs and
  cached "nothing to repair" results.
- Separate tag-change notifications from dimension-only repair completion.
  Both browsers avoid unnecessary recounts for repairs; the secondary browser
  now counts paginated tags from its database instead of an empty image list.
- Bind deferred thumbnail-cache flags to their owning database and deduplicate
  writes. A folder switch cannot redirect old relative filenames to the new DB.
- Skip geometry collection for unchanged masonry windows. Detect replacement
  page objects and dataset generations so this optimization cannot reuse a
  layout merely because the page numbers stayed the same.
- Avoid assembling caption text during grid/masonry delegate painting. Native
  list mode continues requesting its displayed text normally.

## Evidence and limits

An in-memory 8,000-image probe measured dimension application at roughly
240–320 ms before path caching and about 1–2 ms with keys prepared by the worker.
This measures that callback, not total jump latency.

Focused regression checks cover cancellation with both page workers occupied,
replacement requests, folder identity, queued repair delivery, duplicate
filenames, path renaming, tag notifications, and geometry reuse. The final
focused run passed 35 checks across cancellation, masonry geometry, thumbnail
cache, and window planning.

Isolated offscreen Qt probes use temporary settings/media/cache roots, disabled
thumbnail-cache writes, and synthetic media. They passed:

- 80 landings across first/last/middle pages, including a partial last page,
  960 wheel events, and 188 checked selections.
- The actual page-worker delivery path: 36 landings, 432 wheel events, and
  86 checked selections.
- Replacement jumps issued 150 ms after an earlier request: 24 final landings,
  288 wheel events, and 57 checked selections, with no reported failures.
- Startup-restore positioning: 24 centered landings, 288 wheel events, and
  54 checked selections, with no reported failures.
- Arrival of tall upper pages while preserving the landed image, plus view-mode
  switching. The visible item remained index 3000 while its document coordinate
  shifted to accommodate the upper pages.

The longer synthetic runs still recorded occasional event-loop gaps around
50–75 ms. They do not establish real-disk or full-viewer responsiveness.

Remaining synchronous costs include initial filtered-page loading in
`ImageListModel.apply_filter`, database counts for actual tag changes, and
full-resolution decoding in `ImageViewer._load_image_impl`. Page cancellation
also cannot interrupt a single filesystem read or SQL operation already in
progress. These need separate measured changes rather than blanket claims
that background workers make every input path nonblocking.

## Manual check

After a cold restart, jump to a distant page and immediately wheel both above
and below its starting line. Click several visible images while neighboring
pages arrive. Repeat with a second jump before the first finishes, visit the
last partial page, then change sort/filter and check that repairs and selection
still follow the current dataset. Also check folder switching and secondary
browser tag counts.
