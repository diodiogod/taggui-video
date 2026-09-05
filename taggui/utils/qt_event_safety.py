"""Defensive helpers for Qt event wrappers crossing native callbacks."""

from __future__ import annotations

try:
    from shiboken6 import isValid as _is_valid_qt_wrapper
except Exception:  # pragma: no cover - PySide always provides this at runtime
    _is_valid_qt_wrapper = None


def safe_event_type(event):
    """Return an event type only while its wrapped C++ object is alive."""
    if event is None:
        return None
    if _is_valid_qt_wrapper is not None:
        try:
            if not _is_valid_qt_wrapper(event):
                return None
        except (RuntimeError, TypeError):
            return None
    try:
        return event.type()
    except (RuntimeError, TypeError, AttributeError):
        return None
