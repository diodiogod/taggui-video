# TagGUI Video 1M

<img src='images/icon.png' alt='TagGUI icon' width='128'>

TagGUI Video 1M is a fork of TagGUI focused on:

- image + video dataset workflows
- high-speed media visualization
- large-library masonry browsing (toward 1M-scale usability)

This project has evolved far beyond the original image-tagging scope.

---

## What It Is Now

- Media tagging/editor for images and videos
- Multi-view playback workflows (spawned/floating viewers)
- Skin-customizable video controls with live designer
- Ongoing large-dataset architecture work (`windowed_strict` path)

---

## Current Status

Large dataset support is actively improving, but 1M-scale UX is still a work in progress.

The recommended path for current testing is:

- masonry strategy: `windowed_strict`

Legacy strategies exist and are being phased out.

---

## Quick Start

### Windows (recommended)

Run:

```bat
start_windows.bat
```

### Manual launch

```bash
python taggui/run_gui.py
```

Python 3.12 is recommended.

---

## Documentation Map

Start here:

- `docs/GETTING_STARTED.md`
- `docs/FEATURE_OVERVIEW.md`
- `docs/LARGE_DATASET_GUIDE.md`
- `docs/VIDEO_WORKFLOW_GUIDE.md`
- `docs/SKIN_DESIGNER_GUIDE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/MIGRATION_NOTES_FROM_TAGGUI.md`

Existing technical/reference docs:

- `docs/INDEX.md`
- `docs/VIDEO_PLAYER_SKINS.md`
- `docs/FLOATING_VIEWERS_USER_GUIDE.md`
- `SKIN_SYSTEM.md`

---

## Legacy Full README Reference

The pre-redesign README (full historical content) is preserved here:

- `docs/archive/README_LEGACY_REFERENCE.md`

This keeps previous documentation available while the new docs structure is being migrated in parts.

