from __future__ import annotations

import os
import re
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

from utils.settings import DEFAULT_SETTINGS, settings


_VALID_MODES = {"off", "essential", "verbose"}
_LOG_WRITE_LOCK = threading.Lock()
_RETENTION_SWEEP_LAST: dict[str, float] = {}
_LOG_TRIM_HEADER = "================ TRIMMED OLD LOG HISTORY ================\n"
_CRASH_LOG_HEADER_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}) \| ")
_FATAL_LOG_HEADER_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?) \| ")
_TRACE_LOG_HEADER_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) \[TRACE\] ")


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


def diagnostic_time_prefix() -> str:
    """Return a local wall-clock prefix with millisecond precision."""
    try:
        return f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]"
    except Exception:
        return "[--:--:--.---]"


def _entry_timestamp_from_line(line: str) -> datetime | None:
    """Parse a log entry timestamp from a known header line."""
    text = str(line or "").lstrip("\ufeff")

    match = _CRASH_LOG_HEADER_RE.match(text)
    if match:
        try:
            return datetime.strptime(
                f"{match.group('date')} {match.group('time')}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            return None

    match = _FATAL_LOG_HEADER_RE.match(text)
    if match:
        try:
            return datetime.fromisoformat(match.group("date"))
        except ValueError:
            return None

    match = _TRACE_LOG_HEADER_RE.match(text)
    if match:
        try:
            return datetime.strptime(
                f"{match.group('date')} {match.group('time')}",
                "%Y-%m-%d %H:%M:%S.%f",
            )
        except ValueError:
            return None

    return None


def _retain_recent_entries(text: str, cutoff: datetime | None) -> str:
    if cutoff is None:
        return text

    lines = text.splitlines(keepends=True)
    retained: list[tuple[datetime, list[str]]] = []
    current_entry: list[str] = []
    current_ts: datetime | None = None
    saw_timestamp = False

    for line in lines:
        ts = _entry_timestamp_from_line(line)
        if ts is not None:
            if saw_timestamp and current_entry:
                retained.append((current_ts or ts, current_entry))
            current_entry = [line]
            current_ts = ts
            saw_timestamp = True
            continue

        if saw_timestamp:
            current_entry.append(line)

    if saw_timestamp and current_entry:
        retained.append((current_ts or cutoff, current_entry))

    if not retained:
        return text

    kept_lines = [line for ts, entry in retained if ts >= cutoff for line in entry]
    if not kept_lines:
        return ""

    return "".join(kept_lines)


def _read_tail_text(path: Path, keep_bytes: int) -> str:
    if keep_bytes <= 0:
        return ""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= keep_bytes:
        return ""

    try:
        with path.open("rb") as fh:
            fh.seek(max(0, size - keep_bytes), os.SEEK_SET)
            tail = fh.read()
    except OSError:
        return ""

    return tail.decode("utf-8", errors="replace")


def _trim_text_file(path: Path, *, keep_bytes: int, note: str | None = None) -> None:
    """Keep only the newest portion of a text log file."""
    tail = _read_tail_text(path, keep_bytes)
    if not tail:
        return

    if note is None:
        note = f"Kept last {keep_bytes:,} bytes."

    trimmed = (
        "\n"
        + ("=" * 80)
        + "\n"
        + _LOG_TRIM_HEADER
        + f"{note}\n"
        + ("=" * 80)
        + "\n"
        + tail.lstrip("\ufeff")
    )

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(trimmed)
        os.replace(tmp_path, path)
    except OSError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _rewrite_log_with_retention(
    path: Path,
    *,
    retain_days: int | None = None,
    max_bytes: int | None = None,
    keep_bytes: int | None = None,
) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return

    trimmed_text = text
    if retain_days is not None and retain_days > 0:
        cutoff = datetime.now() - timedelta(days=int(retain_days))
        trimmed_text = _retain_recent_entries(trimmed_text, cutoff)

    if max_bytes is not None:
        encoded_size = len(trimmed_text.encode("utf-8", errors="replace"))
        if encoded_size > int(max_bytes):
            tail_keep = max(0, int(keep_bytes or int(max_bytes * 0.6)))
            tail_text = trimmed_text.encode("utf-8", errors="replace")[-tail_keep:] if tail_keep > 0 else b""
            trimmed_text = (
                "\n"
                + ("=" * 80)
                + "\n"
                + _LOG_TRIM_HEADER
                + f"Retained the newest {tail_keep:,} bytes from {path.name}.\n"
                + ("=" * 80)
                + "\n"
                + tail_text.decode("utf-8", errors="replace").lstrip("\ufeff")
            )

    if trimmed_text == text:
        return

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(trimmed_text)
        os.replace(tmp_path, path)
    except OSError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def append_text_log(
    path: str | Path,
    text: str,
    *,
    max_bytes: int | None = None,
    keep_bytes: int | None = None,
    retain_days: int | None = None,
) -> None:
    """Append text to a log file and trim older history when it grows too large."""
    log_path = Path(path)
    if keep_bytes is None and max_bytes is not None:
        keep_bytes = max(0, int(max_bytes * 0.6))

    with _LOG_WRITE_LOCK:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            return

        if max_bytes is None and retain_days is None:
            return

        try:
            now = time.time()
            should_sweep = False
            if max_bytes is not None:
                try:
                    should_sweep = log_path.stat().st_size > int(max_bytes)
                except OSError:
                    should_sweep = False
            if retain_days is not None and retain_days > 0:
                last_sweep = _RETENTION_SWEEP_LAST.get(str(log_path), 0.0)
                if (now - last_sweep) >= 60.0:
                    should_sweep = True
                    _RETENTION_SWEEP_LAST[str(log_path)] = now
            if should_sweep:
                _rewrite_log_with_retention(
                    log_path,
                    retain_days=retain_days,
                    max_bytes=max_bytes,
                    keep_bytes=keep_bytes,
                )
        except OSError:
            pass
