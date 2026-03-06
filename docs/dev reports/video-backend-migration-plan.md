# Video Backend Migration Plan (Future Work)

## Goal
Improve playback smoothness and multi-viewer stability while keeping current reverse-play behavior functional.

## Current State
1. The app currently uses a hybrid approach in `taggui/widgets/video_player.py`.
2. Forward playback uses Qt Multimedia (`QMediaPlayer`).
3. Negative-speed playback uses OpenCV frame stepping.
4. This is functional, but can stutter when many viewers are active.

## Recommended Direction
1. Keep the current reverse path for now.
2. Prototype a new backend only for forward playback first.
3. Evaluate `mpv` first, then consider `GStreamer` only if `mpv` does not meet requirements.

## Scope (Phase 1)
1. In scope:
- Forward playback backend prototype.
- Multi-viewer resource policy.
- GPU adapter preference behavior.
2. Out of scope:
- Full reverse playback rewrite.
- Skin/designer redesign.
- Export pipeline rewrite.

## Architecture Plan
1. Introduce a backend interface (`PlaybackBackend`) with methods like:
- `load(source)`
- `play()`
- `pause()`
- `seek(frame_or_ms)`
- `set_speed(value)`
- `set_loop(start, end, enabled)`
- `get_position()`
- `shutdown()`
2. Keep current implementation as `QtHybridBackend`.
3. Add `MpvBackend` prototype for forward playback.
4. Keep reverse playback routed to existing OpenCV path initially.

## Multi-Viewer Policy
1. Only one viewer actively decodes at full rate at a time (focused/visible).
2. Background viewers use paused frame or reduced update cadence.
3. Cap simultaneous active playbacks by config.
4. Defer non-critical redraws while drag/resize is happening.

## Benchmark Plan
1. Fixed media set:
- 1080p H.264
- 4K H.264 or H.265
- One short VFR clip
2. Test scenarios:
- 1 viewer
- 3 viewers
- 6+ viewers
3. Metrics:
- UI stutter/jank observations
- dropped frames
- CPU usage
- GPU decode usage
- memory footprint
4. Run the same scenarios for:
- current backend
- prototype backend

## Decision Gates
1. Continue migration only if prototype is better on real workload.
2. Minimum acceptance target:
- smoother UI under 3+ viewers
- fewer dropped frames in normal forward playback
- no seek reliability regressions
3. If targets fail, keep current backend and improve scheduler policy only.

## Rollout Plan
1. Add hidden feature flag: `video_backend = qt | mpv`.
2. Ship with `qt` as default first.
3. Enable `mpv` in advanced/developer settings for testing.
4. Collect crash/stutter feedback.
5. Promote `mpv` only after stable cycle.

## Risks
1. Packaging complexity on Windows (runtime dependencies).
2. Different codec behavior across machines.
3. Event-loop integration challenges with multiple player surfaces.
4. Long-term maintenance cost if dual backends remain.

## Fallback Strategy
1. Keep `qt` backend available during rollout.
2. On backend init failure, auto-fallback to `qt` and log reason.
3. Keep reverse playback path independent until final migration decision.

## References
1. Qt `QMediaPlayer` playback rate notes:
- https://doc.qt.io/qt-6/qmediaplayer.html#setPlaybackRate
2. mpv manual (GPU adapter options):
- https://mpv.io/manual/stable/
3. GStreamer trickmodes and seek behavior:
- https://gstreamer.freedesktop.org/documentation/additional/design/trickmodes.html
- https://gstreamer.freedesktop.org/documentation/additional/design/seeking.html
