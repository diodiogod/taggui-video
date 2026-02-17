# Known Limitations

Current known constraints for the ongoing migration phase.

## Large Dataset UX

- 1M-scale behavior is not finalized.
- Cold path (scan/index/enrich) can still be long and disruptive.
- Jump and masonry convergence in deep regions may still need tuning.

## Strategy/Mode State

- Legacy masonry strategy paths still exist in codebase.
- Project direction is converging on `windowed_strict`.

## Video/UI

- Multi-view playback/control UX is improved but still under active optimization.
- Skin designer parity and usability still have open polish items.

## Documentation

- README redesign is in migration phases.
- Detailed legacy docs remain available in:
  - `docs/archive/README_LEGACY_REFERENCE.md`

