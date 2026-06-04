"""Register optional Pillow codec plugins used by TagGUI."""

from __future__ import annotations

import threading

_plugin_init_lock = threading.Lock()
_plugins_initialized = False


def ensure_pillow_plugins_registered() -> None:
    """Register optional Pillow plugins once for the current process."""
    global _plugins_initialized
    if _plugins_initialized:
        return
    with _plugin_init_lock:
        if _plugins_initialized:
            return

        # Import for side effects: registers decoders with Pillow.
        import pillow_jxl  # noqa: F401

        try:
            import pillow_avif  # noqa: F401
        except Exception:
            pass

        _plugins_initialized = True
