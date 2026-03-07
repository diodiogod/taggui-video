# Installation

[Back to Documentation Hub](HUB.md)

This page covers the current setup path for TagGUI Video 1M.

The intended workflow is:

- clone or download the project
- run the launcher script from the project root
- let the launcher create the environment and start the app

## Requirements

Before you start, make sure you have:

- Python 3.10 or newer
- `git` if you want the launcher to pull updates automatically

For the default launcher path, you do not need to create a virtual environment manually.

## Recommended Install Path

Use the launcher from the project root:

- Windows: `start_windows.bat`
- Linux: `bash start_linux.sh`

The launcher will:

- check that Python is available
- optionally run `git pull`
- create or reuse a `venv`
- install PyTorch for your detected CPU or CUDA setup
- install `requirements.txt`
- start TagGUI

The launcher looks for a virtual environment in:

- `./venv`
- `../venv`

## First Run vs Existing Environment

> [!NOTE]
> The launcher installs dependencies automatically when it creates a new virtual environment.

If the launcher finds an existing `venv`, it reuses it and starts the app without reinstalling `requirements.txt`.

That means after pulling project updates, you may need to run this manually inside the environment:

```bash
pip install -r requirements.txt
```

If the update changes the Torch stack or model features start failing with
errors such as `torchvision::nms`, do not repair it with `pip install -r requirements.txt`.
Use the launcher refresh path instead so `torch` and `torchvision` come from the
same CPU/CUDA wheel index:

```bash
# Windows
start_windows.bat --refresh-torch

# Linux
bash start_linux.sh --refresh-torch
```

## Launcher Flags

Supported launcher flags:

- `--skip-git` to skip `git pull`
- `--clear-cache` to clear the pip cache before launch
- `--clean-old` to uninstall packages that are no longer in `requirements.txt`

Windows also supports:

- `--crash-log` to enable crash diagnostics
- `--no-crash-log` to disable crash diagnostics

## Manual Launch

If your environment is already prepared, you can start the app manually from the project root:

```bash
python run_taggui.py
```

This is a fallback path, not the main recommended setup flow.

## Video Playback Backends

TagGUI supports multiple video backend paths, with MPV as the preferred path.

The app searches for runtime files automatically, but backend availability still depends on what is present on your system.

If a backend is missing, check the video settings page for status and runtime hints.

> [!NOTE]
> In this repository, the Windows MPV runtime is already bundled under `third_party/mpv/windows-x86_64/`. A normal fresh installation from this checkout should not require downloading MPV runtime files manually.

> [!NOTE]
> Playback backends and runtime placement will be documented in more detail in a dedicated backend guide.

## Video Editing Requirements

Video extraction, frame edits, SAR fixes, and related video edit operations rely on `ffmpeg`.

If `ffmpeg` is missing, those editing actions will fail even if the app itself launches correctly.

For video editing workflows, make sure `ffmpeg` is installed and available on your `PATH`.

## Common Setup Problems

- `Python not installed`: install Python 3.10 or newer
- `requirements.txt not found`: run the launcher from the project root
- launcher reuses an old environment after update: run `pip install -r requirements.txt` for normal deps, or `--refresh-torch` for Torch stack issues
- video editing actions fail: install `ffmpeg`
- backend-specific playback issues: check the configured backend and runtime availability in settings

## Related Docs

- [Getting Started](GETTING_STARTED.md)
- [Video Backends](VIDEO_BACKENDS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Known Limitations](KNOWN_LIMITATIONS.md)
- [Video Workflow Guide](VIDEO_WORKFLOW_GUIDE.md)
