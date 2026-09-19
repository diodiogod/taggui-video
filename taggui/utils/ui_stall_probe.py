"""Bounded, on-demand UI heartbeat sampling for navigation diagnostics.

The sampler never touches Qt objects or reads source files. It samples Python
frames only while the UI heartbeat is late, and prints after the UI recovers.
"""

import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer


@dataclass
class _Session:
    thread_id: int
    deadline: float
    heartbeat: float
    label: str
    stop: threading.Event = field(default_factory=threading.Event)
    reports: int = 0
    sampled_heartbeat: float = 0.0
    notices: list[str] = field(default_factory=list)


def _frame_signature(frame):
    frames = []
    while frame is not None:
        code = frame.f_code
        frames.append(f"{Path(code.co_filename).name}:{frame.f_lineno}:{code.co_name}")
        frame = frame.f_back
    return " <- ".join(frames[:8])


def _sample(session, emit=print):
    samples = Counter()
    longest = 0.0
    previous_beat = session.heartbeat

    def report():
        nonlocal longest
        if samples and session.reports < 12:
            stack, count = samples.most_common(1)[0]
            emit(f"[UI STALL] {session.label}: heartbeat gap >= {longest * 1000:.0f}ms; "
                 f"dominant stack ({count}/{sum(samples.values())} samples): {stack}")
            session.reports += 1
        samples.clear()
        longest = 0.0

    while not session.stop.wait(0.05):
        while session.notices:
            emit(session.notices.pop(0))
        now = time.monotonic()
        beat = session.heartbeat
        if beat != previous_beat:
            report()
            previous_beat = beat
        if now >= session.deadline or session.reports >= 12:
            break
        gap = now - beat
        if gap >= 0.2:
            frame = sys._current_frames().get(session.thread_id)
            if frame is not None:
                samples[_frame_signature(frame)] += 1
                session.sampled_heartbeat = beat
            del frame
            longest = max(longest, gap)
    if not session.stop.is_set():
        report()


class UIStallProbe(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._control = {"session": None}
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._beat)
        # Capture plain Python state, not a QObject that may already be deleted.
        self.destroyed.connect(lambda *_args, control=self._control: UIStallProbe._stop_control(control))

    @staticmethod
    def _stop_control(control):
        session = control.get("session")
        if session is not None:
            session.stop.set()

    def start(self, label, duration=90.0):
        self._stop_control(self._control)
        now = time.monotonic()
        session = _Session(threading.get_ident(), now + duration, now, str(label))
        self._control["session"] = session
        self._timer.start()
        threading.Thread(target=_sample, args=(session,), name="ui_stall_probe", daemon=True).start()

    def _beat(self):
        session = self._control["session"]
        now = time.monotonic()
        if session is None or now >= session.deadline or session.reports >= 12:
            self._timer.stop()
            return
        gap = now - session.heartbeat
        if gap >= 0.25 and session.sampled_heartbeat != session.heartbeat:
            # Native code holding the GIL can prevent the sampler itself from
            # running. Record the measured delay without inventing a stack.
            session.notices.append(
                f"[UI STALL] {session.label}: heartbeat gap {gap * 1000:.0f}ms; "
                "no Python sample captured (native/GIL blocking or scheduling)"
            )
            session.reports += 1
        session.heartbeat = now
