# Large Dataset Guide

Guidance for large-library usage and testing.

## Current Architecture Direction

- Primary path: `windowed_strict` masonry strategy
- Goal: stable UX from medium to very large datasets (toward 1M)

## Recommended Testing Scales

- Small: hundreds of files
- Medium: tens of thousands
- Large: hundreds of thousands to 1M

## What to Watch

- cold start scan/index time
- scroll smoothness in unseen regions
- masonry convergence/flicker behavior
- jump-to-page stability

## Important Notes

- Legacy strategy paths are considered transitional.
- 1M-scale UX is still in progress and not considered final.

## Related Docs

- Architecture plan: `docs/PLAN1_1M_images_architecture.md`
- Windowed strict plan: `docs/PLAN2_windowed_strict.md`
- Disabled perf features log: `docs/DISABLED_FEATURES.md`

