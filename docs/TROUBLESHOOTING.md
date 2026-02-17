# Troubleshooting

Common issues and first checks.

## App feels slow or stutters

- Verify current masonry strategy (`windowed_strict` recommended path)
- Test with controls hidden vs visible (video-heavy scenarios)
- Compare cold vs warm cache behavior

## Weird masonry behavior after folder switches

- Reload directory
- Confirm folder does not contain benchmark/cache artifacts
- Re-check sort/media filters

## DB lock errors (`WinError 32`)

- Close all TagGUI instances
- Retry operation that touches `.taggui_index.db`

## Where to look next

- Disabled feature notes: `docs/DISABLED_FEATURES.md`
- Legacy behavior comparisons: `docs/MIGRATION_NOTES_FROM_TAGGUI.md`

