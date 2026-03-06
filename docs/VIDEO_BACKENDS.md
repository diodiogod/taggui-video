# Video Backends

TagGUI Video 1M can run with different video playback backends.

The practical recommendation is:

- use MPV when it is available
- use VLC when needed
- expect backend differences in seeking, looping, and frame behavior

## Available Backend Choices

The settings UI exposes these backend options:

- `qt_hybrid`
- `mpv_experimental`
- `vlc_experimental`

If an experimental backend is selected but not available in the current runtime, TagGUI falls back to `qt_hybrid`.

## Recommended Backend

> [!NOTE]
> MPV is the recommended backend for current video workflows.

MPV is the better fit when you care about:

- loop-marker behavior
- seeking quality
- frame-sensitive review work
- the main video workflow described in the rest of the docs

## VLC

VLC is available as an alternative backend path.

It can still be useful for:

- general playback
- systems where MPV is not available
- fallback testing and comparison

> [!WARNING]
> VLC does not provide the same frame-accuracy behavior for loops and markers. If exact loop timing matters, that difference is important.

## Fallback Behavior

TagGUI resolves the configured backend at runtime.

- if `mpv_experimental` is selected and MPV is available, it uses MPV
- if `vlc_experimental` is selected and VLC is available, it uses VLC
- otherwise it falls back to `qt_hybrid`

This means the selected backend and the backend actually used at runtime may differ if required runtime files are missing.

## Runtime Discovery

TagGUI searches for backend runtime files automatically.

For MPV, it searches under repo-relative locations such as:

- `third_party/mpv/`
- `mpv/`

For VLC, it searches under:

- `third_party/vlc/`
- `vlc/`

Platform-specific subfolders are also checked automatically.

At the moment, this repository bundles the Windows MPV runtime, but not a Linux MPV runtime.

On Linux, `mpv_experimental` may still work if a compatible `libmpv` runtime is available on the system or provided in a repo-local Linux runtime folder.

If Linux users ask for it, bundling a Linux MPV runtime may be added later.

## Windows Runtime Placement

On Windows, the settings UI points to these expected runtime locations:

- MPV: place `libmpv-2.dll` in `third_party/mpv/windows-x86_64/`
- VLC: place `libvlc.dll` and `libvlccore.dll` in `third_party/vlc/windows-x86_64/`

For this repository, the Windows MPV runtime is already bundled under `third_party/mpv/windows-x86_64/`.

That means a normal fresh installation from this checkout should not require downloading MPV runtime files manually.

Manual placement only matters if:

- the checkout is missing the bundled `third_party/mpv/windows-x86_64/` files
- you are using a stripped copy of the project
- you want to repair a broken or incomplete local setup

The settings page also shows:

- whether MPV is currently available
- whether VLC is currently available
- backend load errors
- searched runtime directories

## Settings Page

Use the video settings section when you need to inspect backend state.

That page can show:

- the configured backend
- runtime availability
- load errors
- searched directories
- a Windows shortcut for downloading `libmpv-2.dll`

That download shortcut is mainly useful when the bundled MPV runtime is missing or incomplete.

## Playback vs Processing

Playback backend choice is separate from FFmpeg processing settings.

- playback backend affects viewing, seeking, looping, and live playback behavior
- FFmpeg acceleration settings affect processing operations such as crop, extract, fix, and validation

Do not treat those as the same system.

## When to Change Backends

Consider changing backend when:

- a backend is unavailable on your system
- loop behavior does not match your needs
- you are troubleshooting seeking or playback differences
- you want to compare MPV and VLC behavior on the same clips

## Related Docs

- [Installation](INSTALLATION.md)
- [Video Workflow Guide](VIDEO_WORKFLOW_GUIDE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Known Limitations](KNOWN_LIMITATIONS.md)
