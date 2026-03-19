# Getting Started

[Back to Documentation Hub](HUB.md)

This is the practical entry point for running TagGUI Video 1M.

## Install and Launch

Use the launcher script from the project root.

- Windows: `start_windows.bat`
- Linux: `bash start_linux.sh`

On first run, the launcher will:

- optionally pull the latest Git changes
- create or reuse a local virtual environment
- install PyTorch for your detected CPU/CUDA setup
- install `requirements.txt`
- start the GUI

The launcher looks for a `venv` in the current directory first, then one level above it.

> [!NOTE]
> The launcher now fingerprints `requirements.txt` inside the active `venv`. On first run it installs dependencies normally, and on later runs it automatically reruns `pip install -r requirements.txt` only when the dependency file changed.

> [!IMPORTANT]
> Do not use `pip install -r requirements.txt` to repair PyTorch or `torchvision`.
> The Torch stack is managed by the launcher so CPU/CUDA wheels stay matched.
> If model features such as YOLO fail with errors like `torchvision::nms` or a
> stale Torch version, refresh the stack with:
>
> - Windows: `start_windows.bat --refresh-torch`
> - Linux: `bash start_linux.sh --refresh-torch`

## Useful Launcher Flags

These flags are available on the launcher scripts:

- `--skip-git` to start without running `git pull`
- `--clear-cache` to clear the pip cache before launch
- `--clean-old` to remove packages that are no longer in `requirements.txt`
- `--cuda=cu128` to force a Torch CUDA wheel channel when auto-detection is wrong

Windows also supports:

- `--crash-log` to enable crash diagnostics
- `--no-crash-log` to disable crash diagnostics

If the launcher warns that it could not parse the NVIDIA driver version, rerun
the Torch refresh with an explicit override such as:

- Windows: `start_windows.bat --refresh-torch --cuda=cu128`
- Linux: `bash start_linux.sh --refresh-torch --cuda=cu128`

## Manual Fallback

If you already have the environment prepared and only want to start the app manually from the project root:

- `python run_taggui.py`

Use this path only if you already installed the dependencies yourself. The launcher scripts are the intended default.

## First Session

After the app opens:

- load a media folder
- or drag a folder or supported media file from your file manager into the app to open it
- wait for the initial scan if the folder is large
- use the media selector to switch between `All`, `Images`, and `Videos`
- confirm that browsing, filtering, and tagging behave as expected for your folder

The first open of a large folder can take longer while TagGUI builds its database and thumbnail cache. Later opens should be faster.

## Recommended Next Docs

- [Installation](INSTALLATION.md)
- [Feature Overview](FEATURE_OVERVIEW.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Video Workflow Guide](VIDEO_WORKFLOW_GUIDE.md)
- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Skin Designer Guide](SKIN_DESIGNER_GUIDE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
