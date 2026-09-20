"""UI-side supervisor for the detector process.

The HUD / start-stop button stays in this process so it can always
force-kill recognition, even if YOLO is mid-inference.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from queue import Empty, Full

from PySide6.QtCore import QObject, QRect, QTimer, Signal

from app import diag
from app.capture import qrect_to_physical
from app.config import AppSettings, load_settings
from app.detect import worker
from app.paths import WEIGHTS_FILE
from app.weights import weights_ready

log = diag.setup("ui")
_HEARTBEAT_MS = 60_000


def _offer(queue, payload) -> None:
    if queue is None:
        return
    try:
        queue.put_nowait(payload)
        return
    except Full:
        pass
    try:
        queue.get_nowait()
    except Empty:
        pass
    try:
        queue.put_nowait(payload)
    except Full:
        pass


class DetectRuntime(QObject):
    scene_ready = Signal(list, list, tuple, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = multiprocessing.get_context("spawn")
        self._proc = None
        self._ctrl_q = None
        self._out_q = None
        self._active = False
        self._parking: list[dict] = []
        self._intrusion: list[dict] = []
        self._image_size = (1, 1)
        self._frames = 0
        self._frame_errors = 0
        self._last_frame_at = 0.0
        self._worker_death_logged = False

        self._drain = QTimer(self)
        self._drain.setInterval(50)
        self._drain.timeout.connect(self._drain_results)

        self._beat = QTimer(self)
        self._beat.setInterval(_HEARTBEAT_MS)
        self._beat.timeout.connect(self._heartbeat)

    def is_ready(self) -> bool:
        return weights_ready()

    def prepare(self) -> bool:
        """Load YOLO at app start and keep the worker alive."""
        if not weights_ready():
            log.error("Missing YOLO weights: %s", WEIGHTS_FILE)
            print(f"Missing YOLO weights: {WEIGHTS_FILE}")
            print("Place yolo26l.pt in the Download folder next to the program.")
            return False
        if not self._spawn():
            return False
        if not self._drain.isActive():
            self._drain.start()
        if not self._beat.isActive():
            self._beat.start()
        return True

    def start(self, region: QRect) -> bool:
        if region is None or region.width() < 2 or region.height() < 2:
            return False
        if not self.prepare():
            return False
        settings = load_settings()
        self._active = True
        self._frames = 0
        self._frame_errors = 0
        self._last_frame_at = time.monotonic()
        self._flush_out()
        physical = qrect_to_physical(region)
        log.info(
            "detection start logical=%s physical=%s interval=%.2fs worker_pid=%s | %s",
            (region.x(), region.y(), region.width(), region.height()),
            physical,
            settings.interval_sec,
            self._proc.pid if self._proc is not None else None,
            diag.settings_summary(settings),
        )
        _offer(
            self._ctrl_q,
            {
                "op": "start",
                "region": physical,
                "interval": settings.interval_sec,
                "threads": settings.worker_threads,
                "affinity": settings.worker_cpu_affinity,
            },
        )
        return True

    def pause(self) -> None:
        """Stop inference without unloading YOLO."""
        if self._active:
            log.info("detection stop frames=%d errors=%d", self._frames, self._frame_errors)
        self._active = False
        self._parking = []
        self._intrusion = []
        _offer(self._ctrl_q, {"op": "stop"})
        self._flush_out()

    def resume(self, region: QRect) -> bool:
        return self.start(region)

    def apply_settings(self, settings: AppSettings) -> None:
        self.scene_ready.emit(
            list(self._parking),
            list(self._intrusion),
            self._image_size,
            settings,
        )

    def stop(self) -> None:
        """Stop inference but keep YOLO loaded until shutdown()."""
        self.pause()
        self.scene_ready.emit([], [], self._image_size, load_settings())

    def shutdown(self) -> None:
        log.info("runtime shutdown requested")
        self._drain.stop()
        self._beat.stop()
        self._active = False
        _offer(self._ctrl_q, {"op": "quit"})
        proc = self._proc
        if proc is not None and proc.is_alive():
            proc.join(timeout=0.6)
        self._kill_worker()

    def _spawn(self) -> bool:
        if self._proc is not None and self._proc.is_alive():
            return True
        if self._proc is not None:
            log.warning(
                "detector process pid=%s is dead (exitcode=%s), respawning",
                self._proc.pid,
                self._proc.exitcode,
            )
        self._kill_worker()
        try:
            self._ctrl_q = self._ctx.Queue(maxsize=8)
            self._out_q = self._ctx.Queue(maxsize=8)
            proc = self._ctx.Process(
                target=worker.run,
                args=(str(WEIGHTS_FILE), self._ctrl_q, self._out_q),
                daemon=True,
                name="carfind-detect",
            )
            proc.start()
            self._proc = proc
            self._worker_death_logged = False
            log.info("detector process spawned pid=%s", proc.pid)
            return True
        except Exception as exc:
            log.error("Failed to start detector process", exc_info=True)
            print(f"Failed to start detector process: {exc}")
            self._kill_worker()
            return False

    def _flush_out(self) -> None:
        if self._out_q is None:
            return
        while True:
            try:
                self._out_q.get_nowait()
            except Empty:
                break

    def _kill_worker(self) -> None:
        proc = self._proc
        self._proc = None
        self._ctrl_q = None
        self._out_q = None
        if proc is None:
            return
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=0.15)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=0.15)
        log.info("detector process pid=%s terminated exitcode=%s", proc.pid, proc.exitcode)

    def _check_worker_alive(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        if proc.is_alive():
            return True
        if not self._worker_death_logged:
            self._worker_death_logged = True
            log.error(
                "detector process pid=%s died unexpectedly exitcode=%s active=%s "
                "frames=%d last_frame_age=%.0fs (detection is stalled until stop/start)",
                proc.pid,
                proc.exitcode,
                self._active,
                self._frames,
                time.monotonic() - self._last_frame_at if self._last_frame_at else -1,
            )
        return False

    def _heartbeat(self) -> None:
        alive = self._check_worker_alive()
        age = time.monotonic() - self._last_frame_at if self._last_frame_at else -1
        log.info(
            "heartbeat active=%s worker_alive=%s frames=%d errors=%d last_frame_age=%.0fs | ui %s | worker %s | %s",
            self._active,
            alive,
            self._frames,
            self._frame_errors,
            age,
            diag.sample_process(os.getpid()),
            diag.sample_process(self._proc.pid if self._proc is not None else None),
            diag.system_load(),
        )
        if self._active and alive and age > 30:
            log.warning("no detection result for %.0fs while active", age)

    def _drain_results(self) -> None:
        if self._out_q is None or not self._active:
            return
        changed = False
        while True:
            try:
                msg = self._out_q.get_nowait()
            except Empty:
                break
            parking = list(msg.get("parking") or [])
            intrusion = list(msg.get("intrusion") or [])
            size = msg.get("image_size")
            if isinstance(size, (tuple, list)) and len(size) == 2:
                self._image_size = (max(1, int(size[0])), max(1, int(size[1])))
            self._parking = parking
            self._intrusion = intrusion
            self._frames += 1
            self._last_frame_at = time.monotonic()
            if msg.get("error"):
                self._frame_errors += 1
                if self._frame_errors <= 5:
                    log.warning("worker frame error: %s", msg.get("error"))
            changed = True
        if not changed:
            self._check_worker_alive()
        if changed and self._active:
            self.scene_ready.emit(
                list(self._parking),
                list(self._intrusion),
                self._image_size,
                load_settings(),
            )
