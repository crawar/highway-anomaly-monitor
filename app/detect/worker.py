"""Single detector process: one YOLO load, then split results by pipeline."""

from __future__ import annotations

import ctypes
import os
import time
from queue import Empty

from app import diag
from app.detect import (
    ALL_CLASS_IDS,
    COCO_FALLBACK,
    DEFAULT_WORKER_THREADS,
    WORKER_THREADS_MAX,
    WORKER_THREADS_MIN,
    intrusion,
    parking,
)
from app.paths import YOLO_HOME, ensure_download_dir

_REPORT_SEC = 60.0
_FIRST_FRAMES_LOGGED = 3
_ERROR_LOG_LIMIT = 5
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _kernel32():
    """kernel32 with 64-bit-safe prototypes (GetCurrentProcess returns a pseudo-handle of -1)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.SetPriorityClass.restype = ctypes.c_int
    k32.GetProcessAffinityMask.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k32.GetProcessAffinityMask.restype = ctypes.c_int
    k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    k32.SetProcessAffinityMask.restype = ctypes.c_int
    return k32


def _lower_priority(log) -> None:
    """Run below normal so the monitored video client always wins the CPU."""
    try:
        k32 = _kernel32()
        if k32.SetPriorityClass(k32.GetCurrentProcess(), _BELOW_NORMAL_PRIORITY_CLASS):
            log.info("process priority set to below normal")
        else:
            log.warning("SetPriorityClass failed (%d)", ctypes.get_last_error())
    except Exception as exc:
        log.warning("cannot lower process priority: %s", exc)


def parse_cpu_list(spec: str, cpu_count: int) -> list[int]:
    """'16-23,5' -> [5, 16, ..., 23]; invalid / out-of-range entries are dropped."""
    cpus: set[int] = set()
    for part in str(spec or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            try:
                a, b = int(lo), int(hi)
            except ValueError:
                continue
            if a > b:
                a, b = b, a
            cpus.update(range(a, b + 1))
        else:
            try:
                cpus.add(int(part))
            except ValueError:
                continue
    return sorted(c for c in cpus if 0 <= c < cpu_count)


class _Affinity:
    """Apply / restore the process CPU mask (affects every thread, incl. OpenMP)."""

    def __init__(self, log) -> None:
        self._log = log
        self._system_mask = 0
        self._current = ""
        self._k32 = None
        try:
            self._k32 = _kernel32()
            proc = ctypes.c_size_t()
            system = ctypes.c_size_t()
            if self._k32.GetProcessAffinityMask(
                self._k32.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(system)
            ):
                self._system_mask = int(system.value) or int(proc.value)
        except Exception as exc:
            log.warning("cannot query CPU affinity: %s", exc)

    def apply(self, spec: str) -> None:
        spec = str(spec or "").strip()
        if spec == self._current or not self._system_mask or self._k32 is None:
            return
        cpus = parse_cpu_list(spec, (os.cpu_count() or 1))
        if spec and not cpus:
            self._log.warning("worker_cpu_affinity=%r has no valid CPUs, ignored", spec)
            return
        mask = 0
        for cpu in cpus:
            mask |= 1 << cpu
        mask &= self._system_mask
        if not mask:
            mask = self._system_mask
        try:
            k32 = self._k32
            if k32.SetProcessAffinityMask(k32.GetCurrentProcess(), ctypes.c_size_t(mask)):
                self._current = spec
                self._log.info("cpu affinity %s -> cpus=%s mask=0x%x", spec or "(all)", cpus or "all", mask)
            else:
                self._log.warning("SetProcessAffinityMask failed (%d)", ctypes.get_last_error())
        except Exception as exc:
            self._log.warning("cannot set CPU affinity: %s", exc)


def _clamp_threads(value) -> int:
    try:
        threads = int(round(float(value)))
    except (TypeError, ValueError):
        threads = DEFAULT_WORKER_THREADS
    return min(WORKER_THREADS_MAX, max(WORKER_THREADS_MIN, threads))


def _parse_items(results) -> list[dict]:
    items: list[dict] = []
    for result in results:
        if result.boxes is None:
            continue
        names = result.names or {}
        for box in result.boxes:
            cls_id = int(box.cls[0])
            if isinstance(names, dict):
                name = names.get(cls_id, names.get(str(cls_id)))
            else:
                name = names[cls_id]
            if not name:
                name = COCO_FALLBACK.get(cls_id, cls_id)
            items.append(
                {
                    "name": str(name),
                    "cls_id": cls_id,
                    "conf": float(box.conf[0]),
                    "xyxy": [float(v) for v in box.xyxy[0].tolist()],
                }
            )
    return items


def _grab_bgr(sct, region: dict):
    import numpy as np

    raw = sct.grab(region)
    arr = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(raw.height, raw.width, 4)
    return np.ascontiguousarray(arr[:, :, :3])


class _Stats:
    """Per-window frame statistics for the 60 s summary line."""

    def __init__(self) -> None:
        self.total_frames = 0
        self.reset()

    def reset(self) -> None:
        self.frames = 0
        self.errors = 0
        self.over_interval = 0
        self.grab_ms = 0.0
        self.infer_ms = 0.0
        self.max_infer_ms = 0.0
        self.max_total_ms = 0.0
        self.since = time.monotonic()

    def add(self, grab_ms: float, infer_ms: float, interval: float) -> None:
        self.frames += 1
        self.total_frames += 1
        self.grab_ms += grab_ms
        self.infer_ms += infer_ms
        self.max_infer_ms = max(self.max_infer_ms, infer_ms)
        total = grab_ms + infer_ms
        self.max_total_ms = max(self.max_total_ms, total)
        if total >= interval * 1000.0:
            self.over_interval += 1

    def summary(self, interval: float) -> str:
        n = max(1, self.frames)
        span = max(0.001, time.monotonic() - self.since)
        return (
            f"frames={self.frames} ({self.frames / span:.2f}/s, total={self.total_frames}) "
            f"errors={self.errors} interval={interval:.2f}s "
            f"grab_avg={self.grab_ms / n:.0f}ms infer_avg={self.infer_ms / n:.0f}ms "
            f"infer_max={self.max_infer_ms:.0f}ms frame_max={self.max_total_ms:.0f}ms "
            f"over_interval={self.over_interval}"
        )


def run(weights: str, ctrl_q, out_q) -> None:
    ensure_download_dir()
    log = diag.setup("worker")
    diag.install_excepthooks(log)
    diag.log_environment(log)
    reason = "unknown"
    try:
        reason = _run(weights, ctrl_q, out_q, log)
    except BaseException as exc:
        reason = f"exception {exc.__class__.__name__}: {exc}"
        log.critical("detector process aborted", exc_info=True)
        raise
    finally:
        log.info("detector process exiting (%s) %s", reason, diag.sample_process(os.getpid()))


def _run(weights: str, ctrl_q, out_q, log) -> str:
    os.environ["YOLO_CONFIG_DIR"] = str(YOLO_HOME)
    os.environ["YOLO_OFFLINE"] = "True"
    os.environ["ULTRALYTICS_OFFLINE"] = "1"
    # The UI parent pins its own BLAS/OpenMP pools to 1 thread and we inherit
    # that environment; size the OpenMP pool here before torch is imported.
    threads = DEFAULT_WORKER_THREADS
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["MKL_NUM_THREADS"] = str(threads)

    _lower_priority(log)
    affinity = _Affinity(log)

    t0 = time.perf_counter()
    import mss
    # ultralytics must be imported before torch: it sets OMP_NUM_THREADS and the
    # torch thread count on import. Importing torch first initialises the OpenMP
    # pool with every core (measured: 56 threads / 1.4 GB vs 21 threads / 0.75 GB).
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS
    from ultralytics.utils import torch_utils as _tu
    import torch

    try:
        SETTINGS.update({"sync": False})
    except Exception:
        pass

    def _set_threads(n: int) -> None:
        nonlocal threads
        threads = _clamp_threads(n)
        # select_device() resets torch to ultralytics' NUM_THREADS (8) on the
        # first CPU predict; point that constant at our value as well.
        try:
            _tu.NUM_THREADS = threads
        except Exception:
            pass
        try:
            torch.set_num_threads(threads)
        except Exception as exc:
            log.warning("torch.set_num_threads(%d) failed: %s", threads, exc)

    _set_threads(threads)
    log.info(
        "imports done in %.1fs torch=%s threads=%d cuda=%s mss=%s",
        time.perf_counter() - t0,
        torch.__version__,
        torch.get_num_threads(),
        torch.cuda.is_available(),
        getattr(mss, "__version__", "?"),
    )

    t0 = time.perf_counter()
    model = YOLO(weights)
    log.info("model loaded in %.1fs from %s | %s", time.perf_counter() - t0, weights, diag.sample_process(os.getpid()))

    sct = mss.mss()
    ids = list(ALL_CLASS_IDS)
    region: dict | None = None
    interval = 1.0
    active = False
    last = 0.0
    stats = _Stats()
    last_report = time.monotonic()
    error_logged = 0
    reason = "loop ended"

    try:
        while True:
            try:
                cmd = ctrl_q.get(timeout=0.05)
            except Empty:
                cmd = None
            except Exception:
                log.error("control queue broken, leaving loop", exc_info=True)
                reason = "control queue broken"
                break
            if cmd is not None:
                op = cmd.get("op")
                if op == "quit":
                    reason = "quit command"
                    break
                if op == "stop":
                    if active:
                        log.info("stop | %s", stats.summary(interval))
                    active = False
                elif op == "start":
                    region = cmd.get("region")
                    interval = max(0.2, float(cmd.get("interval") or 1.0))
                    if cmd.get("threads") is not None:
                        _set_threads(cmd.get("threads"))
                    affinity.apply(cmd.get("affinity") or "")
                    active = True
                    last = 0.0
                    stats.reset()
                    last_report = time.monotonic()
                    error_logged = 0
                    log.info(
                        "start region=%s interval=%.2fs threads=%d",
                        region,
                        interval,
                        torch.get_num_threads(),
                    )
            if not active or not region:
                continue
            now = time.monotonic()
            if now - last < interval:
                continue
            last = now
            try:
                t_grab = time.perf_counter()
                frame = _grab_bgr(sct, region)
                # predict() may reuse the buffer. Keep the grabbed pixels so the
                # saved alert image is exactly the frame YOLO scored.
                detected = frame.copy()
                t_infer = time.perf_counter()
                h, w = detected.shape[:2]
                results = model.predict(
                    source=detected,
                    classes=ids,
                    conf=0.05,
                    device="cpu",
                    imgsz=640,
                    verbose=False,
                    max_det=100,
                )
                t_done = time.perf_counter()
                items = _parse_items(results)
                out_q.put(
                    {
                        "parking": parking.split_items(items),
                        "intrusion": intrusion.split_items(items),
                        "image_size": (w, h),
                        "frame": frame,
                    }
                )
                grab_ms = (t_infer - t_grab) * 1000.0
                infer_ms = (t_done - t_infer) * 1000.0
                stats.add(grab_ms, infer_ms, interval)
                if torch.get_num_threads() != threads:
                    # ultralytics' first-predict device setup may have changed it.
                    torch.set_num_threads(threads)
                if stats.total_frames <= _FIRST_FRAMES_LOGGED:
                    log.info(
                        "frame %d: %dx%d grab=%.0fms infer=%.0fms items=%d torch_threads=%d",
                        stats.total_frames,
                        w,
                        h,
                        grab_ms,
                        infer_ms,
                        len(items),
                        torch.get_num_threads(),
                    )
            except Exception as exc:
                stats.errors += 1
                if error_logged < _ERROR_LOG_LIMIT:
                    error_logged += 1
                    log.warning("frame failed: %s", exc, exc_info=True)
                try:
                    out_q.put(
                        {
                            "parking": [],
                            "intrusion": [],
                            "image_size": (0, 0),
                            "error": str(exc),
                        }
                    )
                except Exception:
                    log.error("result queue broken", exc_info=True)
            if now - last_report >= _REPORT_SEC:
                last_report = now
                log.info(
                    "%s | %s | %s",
                    stats.summary(interval),
                    diag.sample_process(os.getpid()),
                    diag.system_load(),
                )
                stats.reset()
    finally:
        try:
            sct.close()
        except Exception:
            pass
    return reason
