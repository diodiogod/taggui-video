# Startup Flags

[Back to Documentation Hub](HUB.md)

This page documents the current startup flags accepted by `taggui/run_gui.py`.

These flags are mainly useful when you want to:

- open a folder directly at launch
- start in a limited folder view for very large folders
- tune startup responsiveness
- compare plain-color fast Qt startup against normal system colors

## Recommended Usage

For normal use, keep it simple:

```bash
python run_taggui.py "/path/to/folder"
```

For very large folders, the most useful startup option is a limited view:

```bash
python run_taggui.py --limit 50 --sort-by mtime --sort-dir desc "/path/to/folder"
```

That opens a smaller working set first, then lets background validation catch up later.

## Open Targets

- `target`
  Opens a folder directly, or opens the parent folder of a file and tries to select that file.

- `--open PATH`
  Explicit form of the same behavior. Useful for integrations and scripts.

- `--reuse-instance`
  Sends the open request to an already-running TagGUI instance instead of starting a separate window.

## Limited Folder View

These flags are designed for large folders where opening the full dataset immediately is expensive.

- `--limit N`
  Opens only `N` items initially.

- `--sort-by mtime|name|rating`
  Chooses how the limited set is selected.

- `--sort-dir asc|desc`
  Chooses ascending or descending selection order.

Examples:

```bash
python run_taggui.py --limit 50 --sort-by mtime --sort-dir desc "/path/to/folder"
python run_taggui.py --limit 200 --sort-by name --sort-dir asc "/path/to/folder"
```

Notes:

- `mtime desc` is the main "open the newest files first" workflow.
- `rating` depends on an existing folder database.
- limited mode does not destroy the full folder database; it only changes what is opened first.

## Qt Startup Style Flags

These flags control the startup theme/performance tradeoff.

- `--fast-qt-startup`
  Forces the fast Qt startup path.

- `--no-fast-qt-startup`
  Disables the fast Qt startup path.

- `--qt-system-colors`
  Keeps normal system/theme colors.

- `--qt-plain-colors`
  Uses the plainer fastest-color path instead of system colors.

Current default behavior:

- fast Qt startup is enabled by default
- system colors are also the default
- plain colors are opt-in

## Diagnostics

- `--startup-profile`
  Prints extra startup timing checkpoints so you can see where startup time is going.

Useful when comparing different launch modes:

```bash
python run_taggui.py --startup-profile "/path/to/folder"
python run_taggui.py --limit 50 --sort-by mtime --sort-dir desc --startup-profile "/path/to/folder"
```

## Advanced Startup Tuning

These flags exist mainly for debugging and performance experiments.

- `--background-validation-delay-ms N`
  Delays normal background validation after startup.

- `--limited-validation-delay-ms N`
  Delays background validation for limited folder views.

- `--skip-limited-validation`
  Skips the limited-mode validation pass for that launch.

- `--secondary-restore-delay-ms N`
  Delays Browser 2 startup folder restore.

- `--auto-marking-delay-ms N`
  Delays auto-marking startup initialization.

These are not the first flags to reach for. Prefer trying `--limit`, `--sort-by`, and `--startup-profile` first.

## Launcher Examples

The launcher scripts pass app arguments through to TagGUI.

Windows:

```bat
start_windows.bat --limit 50 --sort-by mtime --sort-dir desc "G:\Downloads\zDowp"
start_windows.bat --startup-profile "G:\Downloads\zDowp"
```

Linux:

```bash
bash start_linux.sh --limit 50 --sort-by mtime --sort-dir desc "/home/user/images"
bash start_linux.sh --startup-profile "/home/user/images"
```

## Related Docs

- [Installation](INSTALLATION.md)
- [Getting Started](GETTING_STARTED.md)
- [Troubleshooting](TROUBLESHOOTING.md)
