"""Play alert WAVs once at a time, without queuing."""

from __future__ import annotations

import wave
import winsound
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QCursor

from app import diag
from app.paths import INTRUSION_WAV, PARKING_WAV

log = diag.setup("ui")

_SND_FILENAME = 0x00020000
_SND_ASYNC = 0x0001
_SND_PURGE = 0x0040
_SND_NODEFAULT = 0x0002

_KIND_PATH = {
    "intrusion": INTRUSION_WAV,
    "parking": PARKING_WAV,
}


def duration_ms(path: Path | str) -> int:
    target = Path(path)
    try:
        with wave.open(str(target), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate() or 1
            return max(1, int(round(frames * 1000 / rate)))
    except Exception:
        return 2000


def play_once(path: Path | str) -> int:
    target = Path(path)
    if not target.is_file():
        log.warning("Missing warning sound: %s", target)
        return 0
    winsound.PlaySound(
        str(target),
        _SND_FILENAME | _SND_ASYNC | _SND_NODEFAULT,
    )
    return duration_ms(target) + 80


def stop() -> None:
    winsound.PlaySound(None, _SND_PURGE)


class VoicePlayer(QObject):
    """Play at most one clip. A new alert never queues behind the current one.

    While an alert remains, the matching clip starts again after the current
    clip ends. When alerts clear, the last clip is allowed to finish.
    stop() still interrupts immediately.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._wanted: str | None = None
        self._playing = False
        self._done = QTimer(self)
        self._done.setSingleShot(True)
        self._done.timeout.connect(self._on_finished)
        self._watch = QTimer(self)
        self._watch.setInterval(40)
        self._watch.timeout.connect(self._on_watch)
        self._arm = QTimer(self)
        self._arm.setSingleShot(True)
        self._arm.setInterval(220)
        self._arm.timeout.connect(self._arm_watch)
        self._watch_pos = None
        self._watch_armed = False

    def play_one(self, kind: str | None) -> int:
        """Play a single clip and do not repeat. Returns duration in ms."""
        self.stop()
        if kind not in _KIND_PATH:
            return 0
        self._wanted = None
        self._start(kind)
        return duration_ms(_KIND_PATH[kind]) + 80 if self._playing else 0

    def update(self, kind: str | None) -> None:
        self._wanted = kind if kind in _KIND_PATH else None
        if self._playing:
            return
        if self._wanted is None:
            return
        self._start(self._wanted)

    def loop_until_move(self, kind: str | None) -> None:
        """Keep repeating an alert clip until the cursor actually moves."""
        self.stop()
        if kind not in _KIND_PATH:
            return
        self.update(kind)
        self._watch_pos = QCursor.pos()
        self._watch_armed = False
        self._arm.start()

    def stop(self) -> None:
        self._wanted = None
        self._playing = False
        self._done.stop()
        self._arm.stop()
        self._watch.stop()
        self._watch_armed = False
        self._watch_pos = None
        stop()

    def _arm_watch(self) -> None:
        self._watch_pos = QCursor.pos()
        self._watch_armed = True
        if not self._watch.isActive():
            self._watch.start()

    def _on_watch(self) -> None:
        if not self._watch_armed or self._watch_pos is None:
            return
        cur = QCursor.pos()
        dx = abs(cur.x() - self._watch_pos.x())
        dy = abs(cur.y() - self._watch_pos.y())
        if dx + dy >= 8:
            self.stop()

    def _start(self, kind: str) -> None:
        ms = play_once(_KIND_PATH[kind])
        if ms <= 0:
            self._playing = False
            return
        self._playing = True
        self._done.start(ms)

    def _on_finished(self) -> None:
        self._playing = False
        if self._wanted is not None:
            self._start(self._wanted)
