# Performance implementation

Baseline: 45f749d (1.6.17). User authorized implementation of worthwhile research findings on 2026-10-02, then reported smooth browsing and requested an intermediate Git checkpoint. This checkpoint includes the implementation, tests and research documents. No push or application version bump is authorized.

Research findings are inputs, not a list of mandatory speculative changes. Implement correctness prerequisites and complete asynchronous lifecycles first; preserve editing, arbitrary navigation, Windows support and video play intent. Reject ideas already ruled out in the research assessment. Record measurements separately from perceived GUI improvements.

## Checkpoint scope

- H1/H2: canonical rank ordering and shared cache freshness.
- H7/H8: owned thumbnail freshness and checked atomic publication.
- H10/M13: bounded explicit scopes and compact order cache identities.
- H3/H4: bounded owned image decoding and asynchronous filter preparation.
- H5/H6: hidden folder work and unused geometry scans.

Tests use `tests/run_isolated.py` to redirect settings, home and derived cache/state before importing services. Database/media fixtures must remain below pytest temporary roots. The user reports that browsing looks smooth and good; this is initial hands-on feedback, not exhaustive editing/comparison/video parity or a measured latency comparison.

## Implemented so far (2026-10-02)

- Canonical page/rank sort terms, including nulls and direction-dependent ties; revision-owned order caches shared safely across connections. Compact numeric view IDs retain four derived orders; old long-key ranks are cleared when a durable order is next built. Explicit large path scopes bind one identity instead of thousands of SQL variables.
- Atomic thumbnail publication reports failure, preserves an existing file, rejects pixels whose source changed before/during publication, and only promotes deferred cached flags when indexed source timestamps still match.
- Bounded latest-request workers prepare full-resolution still images, paginated filter/sort/metadata/stale-file views, tag counts in both browsers, and folder-tree snapshots. Qt scene/model installation remains on the GUI thread. Obsolete requests are canceled and their results rejected. SQLite progress cancellation is restricted to the new request-owned connections.
- Folder trees defer hidden scans and populate visible snapshots in bounded batches. Controlled folder relocation drains the new file/database readers. Shutdown closes their workers.
- Per-file locks now use weak registry ownership while active callers/waiters retain strong references. Removed unused full-resident geometry scans in the blank viewport branch.

## Measurements and checks recorded during implementation

- Generated 4096×3072 JPEG, four warm samples, the committed `_load_image_impl` versus the asynchronous implementation in the same viewer shell: committed handler returned in 69–90 ms, asynchronous handler in 1–4 ms. Accepted installation remained approximately 69–90 ms versus 74–83 ms. Maximum observed 2 ms Qt timer gap was 90.2 ms versus 5.5 ms. This measures handler return/accepted installation, **not first paint or real-folder performance**. The comparison executes the committed handler extracted from Git; it is not a complete baseline application benchmark.
- Generated 26,848-row real schema: two compact orders built in approximately 49 ms each; reuse approximately 0.13 ms. Two views held 53,696 numeric ranks; their long canonical filter descriptions were stored once per view. Write overhead of revision triggers still needs a controlled comparison.
- Earlier broad run: 346 passed, four skipped, 14 failed, with one additional test module excluded because its imported helper does not exist in the checkpoint. The same 14 named failures reproduced in an isolated extraction of commit `45f749d` using only the explicit-settings-path test safeguard. These failures must not be reported as new regressions or as a clean full-suite pass.
- Latest targeted run before the final fixture correction: 51 passed; one new test fixture omitted required `is_video`. Corrected the fixture; subsequent results will be recorded below.

## Safety incident and recovery evidence

The first test runner attempted to redirect Windows QSettings through its default format. The organization/application constructor still selected the real registry store. Five test values were written before the resolved-store assertion stopped the run; application cache/database services had not been initialized. No media or thumbnail cache was modified. The runner now uses an explicit `TAGGUI_SETTINGS_PATH` and verifies both import spellings' actual stores **before any write**.

The accidentally installed temporary thumbnail paths and unused test-only purge key were removed after checking their exact values. A subsequent local-history search recovered user-provided startup logs from September 18–19 showing the normal default thumbnail directory (`~/.taggui_cache/thumbnails`). A read-only registry check confirms that the current fallback resolves to that same directory, which exists and contains WebP entries. No further cache-location write or cache-service initialization was needed. This recovers the effective location; whether the old setting explicitly named that directory or used an empty default is not known.

The extensionless-repair preference was set false and the PNG-cleanup marker true; no record of their original stored values was found. Source-code defaults and isolated probe settings are not evidence of the user's prior preferences. Leave these unchanged pending reliable evidence and do not claim complete restoration. Automatic recovery no longer depends on the user remembering a cache path.

## Remaining gates

- Real Qt lifecycle checks and the relevant broad suite were repeated for the checkpoint; detailed feature parity remains a gate for subsequent changes.
- Preserve editing, comparison, zoom, video transitions and selection behavior. Main still-image decoding is asynchronous; comparison-layer decoding and existing video-backend behavior have not yet been changed.
- Larger thumbnail scheduler, decode-format, indexing/runtime and model-mapping changes remain conditional on their measurements. The research's rejected approaches remain rejected. Persistent explicit-scope membership currently survives in-flight readers; cleanup needs a separate safe lifetime policy.
- A read-only backup of the configured folder's index has now been benchmarked (details below). Initial hands-on browsing feedback is positive; live GUI latency, media/sidecar hydration and detailed feature parity remain measurement/testing gates.

## Follow-up measurements and corrections

- Full suite excluding the checkpoint's uncollectable lazy-video module: **361 passed, four skipped, the same 14 checkpoint failures**, 27.22 s. No additional failures in that run. Later changes receive targeted checks and a final broad run.
- Real Qt tests now cover hidden-tree deferral, latest-root replacement, 3,000-item tree installation yielding to the event loop, and draining open media readers before a Windows rename. Multi-page selections survive the deferred proxy remap. Missing-file recovery repeatedly repopulates complete pages; canceled recursive SQL uses only its own connection.
- The first trigger implementation introduced a measured indexing regression: 26,848 generated image inserts rose from 355–359 ms without revision triggers to 3,132–3,188 ms; 268,480 tag inserts rose from 1,000–1,016 ms to 5,511–5,560 ms. Integer revision storage, BEFORE triggers and no-op trigger bodies did not remove the per-statement cost. This regression was caught before delivery.
- Bounded multi-row INSERTs preserve row order, conflict handling and caller transactions while amortizing statement setup. With all revision triggers enabled, the same fixture measured **209–215 ms for images and 852–873 ms for tags**; the batched no-trigger control measured 181–192 ms and 683–705 ms. These measurements use equivalent generated data/schema, not a real-folder startup run. Application bulk image/tag/marking/caption inserts now use the helper; single-row edits remain ordinary statements. Native cache-bookkeeping columns no longer invoke the revision UPDATE trigger.
- Cached-order reuse now takes the read-only path before requesting SQLite write ownership; a test holds an unrelated writer transaction while reading the already-built order. Builds still acquire write ownership and recheck the revision.
- Sources checked during implementation: [SQLite progress-handler contract](https://www.sqlite.org/c3ref/progress_handler.html) limits cancellation to the owning connection; [SQLite WITH documentation](https://www.sqlite.org/lang_with.html) supports the long-running recursive test workload and cautions against unmeasured materialization hints. No blanket CTE fence or SQLite runtime/DLL replacement was introduced.

## Final automated checkpoint and real index snapshot

- Final checkpoint broad suite: **369 passed, four skipped, the same 14 previously reproduced baseline failures**, 30.47 s. Command: `venv/Scripts/python.exe tests/run_isolated.py tests -q --ignore=tests/test_lazy_video_file_operations.py --tb=no`. That module remains excluded due to its pre-existing missing helper import. The previous broad run had 368 passes in 27.89 s; the subsequent cached-rank change also passed all 22 order-correctness tests plus the real-index snapshot probe. This is not a claim that the repository's entire test suite is green.
- `tests/probe_index_snapshot.py` explicitly opens the configured source index using SQLite `mode=ro` and `query_only=ON`, makes a consistent SQLite backup into a pytest temporary root, closes the source, and only then initializes TagGUI's database service against the copy. Settings/cache/home roots are isolated first by `tests/run_isolated.py`. No source media or sidecar hydration is performed. The original schema, ratings, tags and caches were not altered by this probe.
- Snapshot contained **27,009 images and 288 unique tags**, SQLite 3.45.3. Copy creation took 89–107 ms. First/last 1,000-item page queries for modified/name orders took approximately 0.9–9.1 ms; total tag counts took 2.2–2.3 ms. The rated-filter fixture had no matching tags, so its 2 ms count is not evidence for expensive nonempty filters.
- Random-order first-page preparation took approximately 96 ms, including an 85 ms order build. **Before cached-rank lookup**, locating the last item on the first/last random pages took 118/81 ms. **After**, the corresponding lookups took 0.24/0.11 ms. Cached last-page retrieval took 0.25 ms. Rank correctness is checked against the actual returned order, including cross-connection edits/eviction in generated tests. These are two database snapshot runs, not controlled cold-disk application startup or first-paint measurements.
- A cached-rank regression test verifies that the accepted order is used without another full-dataset count expression. Direct canonical ranking remains the fallback if no matching owned order is available.
- Comparison now retains an owned continuation when its base image is still decoding. Real Qt tests exercise accepted comparison and exiting before decode completion. Full-resolution dimensions and latest-selection rejection are covered; visual zoom/crop/marking/video parity still needs interactive use.

## Implementation scope and next decision

| Research item | Current disposition | Main implementation files | Remaining check |
| --- | --- | --- | --- |
| H1/H2 | Implemented canonical ranking, revision ownership, independent views and cached rank reuse | `utils/image_index_db.py` | Random/deep jumps, edits and two browsers in the real UI |
| H3 | Main still decode implemented, including pending comparison-base ownership | `widgets/image_viewer.py`, `utils/image_decode.py`, `utils/latest_task.py` | Zoom/crop/marks, source overwrite, comparison/spawned viewers, image/video transitions; comparison overlays still decode synchronously |
| H4 | Sort/filter/metadata/stale preparation and both browsers' aggregate counts moved to owned workers | `models/image_list_model.py`, `widgets/image_list_dock.py`, `controllers/signal_manager.py`, `widgets/secondary_browser.py`, `utils/tag_count_loader.py` | Real filter/selection/scroll anchoring, outgoing edits; older refresh branches still have synchronous count work |
| H5/H6 | Hidden folder deferral, background snapshot, bounded GUI tree population, unused geometry scans removed | `widgets/folder_tree_panel.py`, `utils/folder_snapshot.py`, `widgets/image_list_view_layout_mixin.py` | Folder actions/counts, reveal during loading, deep viewport appearance |
| H7/H8 | Implemented source-owned, acknowledged atomic thumbnail saves | `models/image_list_model.py`, `utils/thumbnail_cache.py` | Visual cache parity after edits and real Windows cache-reader contention |
| H9 | Deferred runtime replacement | Python/PyInstaller packaging, `utils/image_index_db.py` | Verify a packaged fixed SQLite runtime and native dependencies; do not substitute a DLL speculatively |
| H10/M13 | Bounded SQL bindings and compact order storage implemented | `utils/image_index_db.py`, model scope setup | Scope lifetime cleanup remains; bulk scope registration can still do synchronous DB work |
| A1/A4, file locks | Incremental request/worker services and weak lock registry implemented | New utility modules, `utils/media_file_lock.py` | Additional extraction should follow measured bottlenecks and GUI parity |
| M1–M15 / A2–A5 remainder | Conditional work retained in research backlog | See assessment | No unmeasured decoder change, full proxy replacement, video redesign, blanket index/pragma tuning or search-semantic change |

The user has approved an intermediate commit after reporting smooth browsing. Continue checking rapid image navigation, distant random-sort jumps with reverse scrolling, applying/clearing filters while preserving selections, editing crop/tags/markings, comparison and image/video transitions, showing the folder tree and switching folders. Approval of this checkpoint does not establish every feature's parity or measured tail latency.

This implementation is being recorded as the user-requested intermediate commit; it will remain unpushed and the application version remains 1.6.17. The former thumbnail-location question has been resolved from local records; the two original preference/marker values remain unknown.

## Remaining implementation candidates

1. **Measure and prioritize thumbnail work after rapid jumps (M4/M5).** Inventory queued/running/completed jobs, retained image bytes, visible-target wait and GUI conversion bursts in `models/image_list_model.py`, the preload/geometry mixins and `utils/thumbnail_cache.py`. Then introduce demand or delivery budgets only where evidence shows a bottleneck. Potentially high impact for cold or rapid navigation; medium confidence in live benefit, medium-to-large effort, medium-to-high regression risk; GUI testing required.
2. **Extend asynchronous ownership to comparison images and remaining refresh paths (H3/H4 remainder).** `widgets/image_viewer.py::_load_static_pixmap_for_proxy_index` still decodes comparison layers synchronously. Some `models/image_list_model.py` refresh/count paths remain synchronous. Reuse the established request ownership while preserving comparison layout, edits and selection. High confidence in these source-level blocking paths, workload-dependent impact, medium effort, medium-to-high regression risk; GUI testing required.
3. **Bound derived scope lifetime and characterize search differences (H10/M12).** `utils/image_index_db.py::register_path_scope` retains membership so active readers are safe; add a proven lifecycle before cleanup. Characterize `models/image_list_model.py::_build_filter_sql` against `models/proxy_image_list_model.py::does_image_match_filter` before changing search behavior. High correctness/storage confidence, medium effort, high compatibility risk for semantic changes; GUI testing required, and the intended search behavior may need a user decision.

The pre-existing test failures and excluded module also deserve separate diagnosis. They were reproduced before this batch; checkpoint approval is not a reason to suppress them or claim a fully passing suite. Larger proxy/navigation rewrites, decoder/runtime changes and video startup changes remain conditional on the original profiling gates.
