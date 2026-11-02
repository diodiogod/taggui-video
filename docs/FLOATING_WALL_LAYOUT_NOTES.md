# Floating Wall Packing

The default `Best fit` searches both the original masonry candidate and
rectangle-packing candidates. `Masonry` and `MaxRects` can be selected separately
in Settings or overridden for the current session from the wall menu.

## Comparison

`tests/benchmark_floating_wall_packing.py` compares 21 deterministic layouts on
a 1908 x 1068 available rectangle, with a six-pixel gap. The cases include
uniform landscape, portrait, and square media, plus mixed aspect ratios with
3, 5, 7, 10, 15, and 24 windows. The score is the sum of the window areas divided
by the available screen area; it excludes media letterboxing and UI overlays.

| Planner | Mean coverage | Median calculation time | Maximum calculation time |
| --- | ---: | ---: | ---: |
| Original masonry | 67.14% | 0.28 ms | 1.03 ms |
| Masonry with fixed-size support | 67.27% | 5.95 ms | 80.68 ms |
| MaxRects | 79.92% | 28.50 ms | 194.53 ms |
| Best fit | 79.92% | 42.06 ms | 348.46 ms |

These are one local run's geometry measurements, not application latency or
general performance guarantees. All 21 layouts fit without overlaps. The
uniform layouts largely tied, while mixed layouts benefited from MaxRects.
Best fit retains masonry as a candidate instead of assuming one heuristic
always wins. Reproduce the comparison with:

```powershell
venv/Scripts/python.exe tests/benchmark_floating_wall_packing.py
```

## Implementation

- `widgets/floating_wall_packing.py` receives only ratios, dimensions, and
  geometry constraints. It evaluates shortest-column masonry and rectpack's
  `MaxRectsBssf`, `MaxRectsBaf`, and `MaxRectsBl`, without rectangle rotation.
- It searches a common scale for windows allowed to resize, preserving their
  proportions and relative size preferences. Kept sizes are exact constraints.
  With automatic sizing disabled, all current sizes become exact constraints.
- Initial packing tries common-width and equal-area size seeds. Repacks use
  current window sizes. Every accepted candidate must fit screen bounds,
  spacing, minimum dimensions, kept sizes, proportions, and optional screen order.
- The primary score is used window area. Ties prefer a smaller bounding region
  and then less movement. These heuristics do not establish global optimality.
- If no candidate fits all windows, no partial layout is installed.
- `controllers/floating_wall_controller.py` sends resize reflow to a `LatestTask`
  worker. A result is accepted only while its window geometry and membership,
  destination screen, and request token are still current.
- Resize reflow keeps the same viewers and video synchronization coordinator.
  MPV geometry changes repaint the existing frame; they do not decode an
  OpenCV fallback frame or change playback intent.

## Relevant Checks

```powershell
venv/Scripts/python.exe tests/run_isolated.py tests/test_floating_wall_packing.py tests/test_floating_wall_reflow.py -q
$env:QT_QPA_PLATFORM = 'windows'
venv/Scripts/python.exe tests/run_isolated.py tests/probe_wall_layout.py -q -s
```

The isolated runner redirects the actual QSettings file and cache/home roots
before importing application services. The native probe creates its own mixed
aspect-ratio videos and exercises real wall opening, asynchronous MPV startup,
ordered-model refresh, resizing, and a shared playback toggle while packing is
pending. It checks expected fixture colors on the active video or still-frame
output path, both initial play/pause states, kept sizes, screen bounds, and
absence of synchronous frame decoding during automatic reflow.

See [the user guide](MASONRY_REVIEW_WALL_GUIDE.md#packing-and-automatic-reflow)
for controls and defaults.


## Anchored drag previews

`wall_anchor_controller.py` intercepts Ctrl-left-drag on wall windows before the
ordinary move/compare handlers. It reserves Escape through ShortcutOverride,
latches the gesture through release, and leaves Alt bypass available. A transparent,
input-pass-through tool window draws ghost rectangles and dark red anchor borders.
A 70 ms timer coalesces geometry changes; a separate LatestTask worker receives
only rectangle data. The GUI thread never waits for the planner. Releasing while
calculation is pending applies only the latest accepted result. Escape, settings
changes, wall membership/geometry changes, lost capture, and close cancel it.

`wall_anchor_packing.py` subtracts padded anchor obstacles from free rectangles,
then tries nearby placements in current and area order at descending common scales.
Anchors are exact position-and-size constraints. Fixed sizes and automatic-sizing
off remain hard constraints. The explicit `anchor_preview` policy retains current sizes when possible during
a drag. Resize/repack requests instead search scales above and below the current
sizes, retaining feasible candidates and refining the largest successful scale. It overrides initial packing
algorithm/alignment/order choices while anchors exist. Like the other planners,
it is heuristic and may reject a feasible arrangement it cannot discover.

Snapping uses logical screen coordinates, a 10 px attraction threshold and 18 px
release threshold. Shift disables it. The gesture stays on the starting screen.
Anchor state belongs to each live window and is not persisted across reopening.
`test_wall_anchors.py` covers obstacle packing, actual Ctrl input, rollback, multiple
anchors, snapping, and native preview border pixels. The native video probe also
exercises Ctrl-drag after real media opening/model refresh in both playback states.


## Resize previews and overlay input

Resize preview work has its own LatestTask and 70 ms coalescing timer. It predicts
release-time size locks without mutating them, uses the ordinary resize/repack
policy, and draws the source destination in amber. Source geometry, wall membership,
screen geometry, and gesture state must still match before a result is displayed.
Release cancels the preview and follows the existing committed reflow path.
Alt bypass, disabled resize reflow, window removal, and lost capture dismiss it.

A host-owned application event filter reserves the existing 12 px viewer border
before child controls consume presses. It delegates to the viewer's actual resize
methods and captures movement/release for that gesture. Close buttons and Ctrl-drag
retain their own handling, and interior control clicks retain their behavior.
The native probe overlaps a real seek button with the corner, tests the viewport
hover zone separately, and checks playback state and expected media pixels.


## Focused layout controls

The wall context menu offers Arrange now, one saved automatic-arrangement switch,
three exclusive window modes, explicit reset actions, the session algorithm choices,
and a focused settings dialog. The former session-only Manual action is removed;
its saved shortcut key is retained and now toggles the same persisted resize-reflow
setting as the menu and panel. There is no second hidden automatic-layout veto.

`dialogs/wall_layout_settings.py` supplies the grouped panel both to the dedicated
modeless dialog and the main Settings page. Changes synchronize between open panels
and the menu. Only one icon is visible per window (position pin takes precedence),
and unpinning restores a separately kept size if present. Flexible removes both
locks. Resetting sizes and unpinning are independent, geometry-preserving actions;
Start fresh releases all locks and explicitly fits even with automatic arrangement off.

Submenu and menuAction Python wrappers are retained for the lifetime of the parent
menu; dropping temporary QAction wrappers can invalidate their QMenu on this PySide
build. Menu tests exercise chained action lookup and repeated state refresh.
