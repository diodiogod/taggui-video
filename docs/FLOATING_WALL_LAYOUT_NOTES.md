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
