from __future__ import annotations

from utils.settings import DEFAULT_SETTINGS, settings


_VALID_MODES = {"off", "essential", "verbose"}


def get_diagnostic_log_mode() -> str:
    """Return the current diagnostic logging mode.

    Modes:
    - off: suppress diagnostic runtime logs
    - essential: keep high-signal user/debug lines only
    - verbose: emit full runtime diagnostics

    Backward compatibility:
    - `minimal_trace_logs=True` maps to `essential`
    - `minimal_trace_logs=False` maps to `verbose`
    """
    try:
        mode = str(
            settings.value(
                "diagnostic_log_mode",
                defaultValue=DEFAULT_SETTINGS.get("diagnostic_log_mode", "essential"),
                type=str,
            )
            or ""
        ).strip().lower()
    except Exception:
        mode = ""
    if mode in _VALID_MODES:
        return mode

    try:
        minimal_trace = bool(settings.value("minimal_trace_logs", True, type=bool))
    except Exception:
        minimal_trace = True
    return "essential" if minimal_trace else "verbose"


def should_emit_diagnostic_log(detail: str = "verbose") -> bool:
    """Return True when a diagnostic line of the given detail should be emitted."""
    mode = get_diagnostic_log_mode()
    if mode == "off":
        return False
    if mode == "verbose":
        return True
    return str(detail).strip().lower() != "verbose"


def should_emit_trace_log(component: str, message: str, *, level: str = "DEBUG") -> bool:
    """Return True when a `[TRACE]` line should be printed."""
    mode = get_diagnostic_log_mode()
    if mode == "off":
        return False
    if mode == "verbose":
        return True

    component = str(component or "").strip().upper()
    message = str(message or "")
    level = str(level or "DEBUG").strip().upper()

    if component == "STRICT":
        return message.startswith("Owner remap(internal)")
    if component == "MASONRY":
        return (
            message.startswith("Strategy=")
            or message.startswith("Waiting target page")
            or message.startswith("Waiting window items")
            or message.startswith("Snap to loaded page")
        )
    if component == "PAGINATION":
        return message.startswith("Triggered loads")
    if component == "PAGE":
        return level == "INFO" and message.startswith("Initial bootstrap complete")
    return False


def diagnostic_print(message: str, *, detail: str = "verbose") -> None:
    """Print a diagnostic line if the current mode allows it."""
    if should_emit_diagnostic_log(detail=detail):
        print(message)
