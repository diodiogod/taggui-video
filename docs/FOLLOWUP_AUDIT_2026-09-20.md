# Follow-up audit — in progress

This is the separate 50-minute audit requested after the masonry audit.
Existing changes remain uncommitted for the user's GUI test.

## Confirmed source paths under investigation

- `ImageListModel.apply_filter` performs the database count and loads up to
  three pages synchronously between model reset signals. Page materialization
  includes filesystem existence checks and metadata sidecar reads. Moving
  only the count would therefore not make filtering responsive.
- `ImageViewer.load_image` calls `_load_image_impl` directly. Static decoding
  through `QImageReader.read`, fallback decoding, pixmap creation, and scene
  initialization all occur in that call. An asynchronous replacement needs
  explicit ownership of selection, image/video transitions, edits, and errors.
- `start_refresh_new_media_only_async` captures sort/filter state, but
  `apply_refresh_new_media_only_result` checks only refresh generation and
  folder identity before applying the preloaded pages. A sort/filter change
  during the scan can make those pages obsolete. Main-window completion also
  restores the filter and selection captured when the refresh began.
- `_schedule_deferred_extension_repair` runs after 250 ms and unconditionally
  persists the repaired image as the selected path. It also resolves the
  source model at callback time. Selection or browser changes during that
  interval require ownership checks before those side effects.

## Scoped fix applied

Deferred extension repair now verifies the image, proxy/source model, folder,
and original path before performing its delayed work. Moving to another image
or folder cancels that stale callback; selecting the image again can schedule
a fresh repair. A focused test reproduces both selection and folder changes,
and verifies that the unchanged selection still repairs and saves its path.

The broader synchronous-loading paths remain under review.

The main window now retains the originating browser/model in the pending
refresh request, including during its delayed start. It serializes requests
through the shared pending state and disables the refresh action until that
state clears. Previously another browser could replace that state while the
first browser's independent worker was still running. This change needs the
two-browser GUI check alongside the other uncommitted fixes.

## Refresh reproduction and implementation constraint

A pure in-memory probe invoked the actual
`apply_refresh_new_media_only_result` method with a current model page
generation of 8 and an old-sort payload. The method accepted and installed
the supplied old page objects because the refresh generation and folder
matched. No application, user settings, database, or media files were opened.

A stale-result rejection alone is insufficient: the worker already indexed
new files, so a later additions-only scan may find nothing new and never
reload the current view. The fix must rebuild the current sort/filter view
from the committed index, preserving the user's current selection/filter,
rather than restoring the state captured when scanning began. The main
window also has one shared pending-refresh state while primary and secondary
models have independent workers; ownership needs reviewing end to end.

The model now records the page generation at scan start. If it changed, it
recounts using the current filter and rebuilds current pages instead of
installing the obsolete payload. An unchanged view retains its prepared
worker pages. The main window checks the live folder and captures the current
selection/filter before applying the result, including an explicitly cleared
filter. Focused checks cover changed and unchanged generations and old folders.

This is a correctness fix, not yet a responsiveness fix: the existing fallback
page rebuild is synchronous. Moving that fallback off-thread without dropping
committed additions remains an audit target.

Refresh snapshots can contain pages from before a jump. A focused reproduction
confirmed that the reload helper installed pages 0 and 1 from an old snapshot
when only page 14 remained resident. It then chose page 0 for enrichment.
The helper now reuses prepared pages only from the current reload set, including
the existing explicit page-zero requirement for additions. The reproduction
passes after this scoped fix. Current resident pages missing from the snapshot
are still loaded synchronously; that broader path has not been redesigned.

## Additional filter callback cost

The primary filter path is `set_image_list_filter` → debounce timer →
`delayed_filter` → proxy `set_filter` → source `apply_filter`. After the
synchronous count/page loads, `filter_changed` also calls proxy `get_list`
and `TagCounterModel.count_tags_filtered`. In paginated mode `get_list`
enumerates only resident rows. Consequently filtered tag counts can describe
only the loaded subset while their tooltip says "current view". This callback
also adds a Qt model walk and tag counting to the same UI turn. A future
off-thread filtering change must address this callback and preserve full-domain
tag-count semantics, not merely move the source page reads.

## Static decoding measurement

A standalone probe generated 4096×3072 RGB noise images in a dedicated
temporary directory and invoked `QImageReader.read()` with auto-transform,
matching the viewer's decoder settings. Three reads per format measured:

| Format | Decode times (ms) |
| --- | --- |
| JPEG | 160.0, 147.8, 158.9 |
| PNG | 209.8, 210.0, 198.1 |
| WebP | 592.3, 559.0, 561.8 |

The probe imported no application services, instantiated no application model,
and touched no user settings/cache/media. Files were freshly generated, so
these are not cold-disk measurements. Pixmap conversion, scene initialization,
caption loading, and other selection callbacks are excluded. Since the actual
viewer executes this decoder call synchronously, it alone can account for a
visible input pause. An asynchronous implementation remains unimplemented;
it must guard result delivery against selection changes and preserve editing,
zoom-follow behavior, videos, and extension-repair fallbacks.

## Follow-up GUI evidence (2026-09-21)

The user's next run landed correctly on global index 9000. The target page took
5.27 seconds to load and positioning completed at 5.56 seconds. After that,
the UI-stall sampler identified `_preload_pagination_pages`, masonry painting,
and repeated `get_video_training_profile` calls from video-badge painting.
This matches the reported behavior: clicking and wheel input worked but felt
blocked until post-jump work settled.

Two scoped changes address the sampled work:

- Thumbnail eviction no longer starts or resumes during scrollbar interaction,
  wheel scrolling, or while explicit jump ownership is settling. Eviction is
  memory cleanup and can safely resume 250 ms later; it should not release
  native pixmaps in the input-critical landing period.
- Video badge painting caches the selected training profile for one second.
  Previously every visible video badge called `QSettings.value()` on every
  paint. The short lifetime still reflects a changed setting without restart.

The trace also showed that the remaining multi-second cold jump is dominated
by loading the target page itself before it becomes visible. That work already
runs off the UI thread. It depends on filesystem/database/cache state and is
separate from the post-position input stalls addressed above.

## Filter correctness and cost

Paginated filtered tag counts previously walked `proxy.get_list()`, which only
contains resident pages. Counts could therefore be incomplete while also doing
extra Qt model work in the filter completion turn. The database now computes
tag counts across the full active SQL filter, and the tag counter installs
those as current-view counts without replacing full-folder totals. Non-paginated
behavior is unchanged.

## Remaining limits

- Full-resolution static image decoding remains synchronous. The measured
  WebP decoder cost can exceed half a second before pixmap/scene work. A safe
  async conversion needs explicit latest-selection ownership and handling for
  edits, videos, extension repair, errors, and zoom-follow state.
- Applying a background refresh after its view changed can still synchronously
  materialize current resident pages. The stale-page correctness bugs were
  fixed, but a fully asynchronous reset/apply pipeline would be a larger model
  lifecycle redesign.
- The user's run still contained owner remaps around the page 9/10 boundary.
  They no longer moved the explicit jump target, but can produce small visual
  shifts as neighboring geometry becomes resident. Further changes should be
  based on a new trace after the eviction and paint fixes rather than another
  speculative masonry strategy change.

## Suggested GUI checks

1. Restart on a saved item deep in the folder; confirm the list restores there.
2. Drag-jump from page 1 to page 10 or later, then immediately wheel both ways
   and click several thumbnails, especially videos.
3. Confirm the straight landing line starts on the requested page and upper
   pages populate without an empty gap.
4. Repeat two distant jumps before the first one's neighboring pages finish;
   confirm the second target owns the result.
5. Apply and clear a tag filter in the large folder; confirm current-view tag
   counts cover the entire result, not only visible/resident pages.
6. Run “Refresh New Media Only” in each browser after changing selection,
   filter, or folder during the scan; confirm stale state is not restored.

## Second follow-up trace (2026-09-21)

The next trace showed a fast page-20 landing (578 ms load, 797 ms positioned)
and a cold page-11 landing (8.30 s load, 8.64 s positioned). After positioning,
three avoidable UI paths were sampled: proxy invalidation during wheel input,
thumbnail preloading consuming completed futures through `DecorationRole`, and
the hidden Quick Sort panel synchronously recounting its eligible database
domain.

The proxy now waits until the 200 ms scroll-idle boundary before rebuilding its
native row mapping. Paginated preloading now submits thumbnail I/O without
performing offscreen QImage-to-QPixmap conversion; visible painting consumes
the result. Quick Sort eligibility recounts stop while the panel is hidden and
defer while a jump or wheel gesture is active. The masonry click fallback also
uses numeric rectangle bounds instead of allocating one QRect per cached item.

The 8.30-second target-page load is separate: the page worker materializes
1,000 records, validates file existence, and reads applicable metadata sidecars.
Removing those checks would change visible-file and sidecar behavior, so this
pass does not bypass them without a dedicated ownership/deferred-hydration
design and measurement.
