# Plan: Open Folder New-Media Watcher

## Goal
Add an optional watcher for the currently open folder so newly copied media can appear without manual refresh.

## Current Baseline
- `Refresh New Media Only` is now the stable manual path for paginated folders.
- It is good enough to keep as the fallback and correctness path.
- The main remaining friction is manual triggering, not full-folder rebuild correctness.

## Scope and Locked Decisions
1. Watch only the currently open folder.
2. Watch only while that folder is open in the app.
3. Additions-only for v1.
4. Keep `Reload Directory` and `Refresh New Media Only` as fallback actions.
5. Make watcher optional and easy to disable.

## Phase 1: Safe Watcher Skeleton
1. Add a folder-watch service owned by the main window or model.
2. Start it when a folder is loaded; stop it on folder switch or app shutdown.
3. Limit v1 to local open-folder watching only.
4. Log watcher start/stop and raw event counts at low noise.

## Phase 2: Event Stabilization
1. Debounce bursts of filesystem events into one refresh batch.
2. Treat files as "ready" only after size and mtime stop changing briefly.
3. Ignore unsupported files and internal app folders.
4. Collapse duplicate create/change events for the same path.

## Phase 3: DB and UI Integration
1. Reuse the existing incremental new-media indexing path.
2. Insert only confirmed new media paths.
3. Refresh only affected loaded pages and counts.
4. Preserve selection, filter, and scroll as much as possible.

## Phase 4: Failure and Fallback Rules
1. If watcher events are ambiguous, do not guess.
2. On rename/delete/move ambiguity, surface a soft notice and keep manual refresh available.
3. If watcher backend fails or overflows, stop watcher cleanly and fall back to manual refresh.

## Acceptance
1. Copying new files into the open folder causes them to appear without a manual click.
2. No full-folder reload is triggered for simple additions.
3. No repeated event storm or duplicate inserts.
4. UI remains responsive during watcher-driven indexing.
5. Turning watcher off restores current manual behavior unchanged.

## Stop Conditions
- If watcher noise on Windows is too high for reliable additions-only batching.
- If cloud/network folders produce unstable half-written files too often.
- If the watcher path becomes less predictable than manual `Refresh New Media Only`.
