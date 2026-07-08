# Bundled MPV Runtime Files

Place platform-specific mpv runtime libraries here to enable `mpv_experimental`
without requiring users to edit system PATH manually.

Expected layout:

```text
third_party/mpv/
  windows-x86_64/
    mpv-1.dll
    # plus any required dependency DLLs
  linux-x86_64/
    libmpv.so
    # or libmpv.so.2
  macos-arm64/
    libmpv.dylib
```

Notes:

1. Runtime discovery is automatic at app startup.
2. If mpv runtime cannot be loaded, TagGUI falls back to `qt_hybrid`.
3. For development on Windows, placing `mpv-1.dll` in `venv/Scripts/` also works.
