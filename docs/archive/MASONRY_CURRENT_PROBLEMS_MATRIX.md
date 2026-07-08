# Masonry Current Problems Matrix

## Scope
`windowed_strict` strategy in paginated mode.

## Legend
- Status: `PASS`, `FLAKY`, `FAIL`

## Scenario Matrix

| Scenario | Expected | Actual (current) | Status |
|---|---|---|---|
| Drag to page ~5 from top | Lands on ~5, page loads, no blank | Usually works now | FLAKY |
| Drag to page ~18 from top | Lands on ~18, stable thumb, page loads | Often loads, but thumb may jump | FLAKY |
| Drag to page ~21/22 (bottom) | Lands on tail, shows tail images, stays interactive | Can enter blank viewport + `Loading target window...` | FAIL |
| Drag back up after tail visit | Smooth return to mid pages | Can remain blank or map erratically | FAIL |
| Repeated drag-release cycles | Deterministic mapping each release | Ownership/range drift appears over time | FAIL |
| Normal wheel scroll after strict drag sessions | Smooth continuous scrolling | Can degrade and show void states | FLAKY |
| Home/End in strict flow | Correct refocus and content | Historically inconsistent; improved but still fragile in strict states | FLAKY |
| End-of-dataset tail fit | Last images visible in bounds | Tail can clip or go blank depending on state | FAIL |

## Repro With Highest Failure Rate
1. Drag to ~5, release.
2. Drag to ~18, release.
3. Drag to ~21/22, release.
4. Drag to ~14, release.

Failure signatures:
- thumb jump
- empty viewport
- persistent `Loading target window...`

## Key Trace Lines to Capture
- `Release slider=... frac=... page=...`
- `Waiting target page ... before strict calc`
- `Calc start: tokens=... window_pages=... current_page=... mode=windowed_strict`
- `Loading target window...`

## Interpretation Notes
- If release target page is correct but content stays blank, strict window readiness/paint recovery failed.
- If release fraction/page looks wrong right after drag, strict domain/range normalization failed.
- If owner appears stable but thumb moves significantly, non-authoritative range writer still exists.
