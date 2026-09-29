"""Field diagnostics: per-process log files under <project>/logs.

Every process (UI and detector worker) writes its own rotating log so the
files can be copied back from a machine where the program misbehaves.
Native crashes are captured by faulthandler into crash-<role>.log.
"""

from __future__ import annotations

import ctypes
import faulthandler
import logging
import os
import platform
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import VERSION
from app.paths import LOG_DIR, ROOT, ensure_log_dir

_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 3
_fault_files: list = []
_procs: dict[int, object] = {}


def log_path(role: str) -> Path:
    return LOG_DIR / f"carfind-{role}.log"


def setup(role: str) -> logging.Logger:
    """Return the logger for this process role, creating the file on first use."""
    logger = logging.getLogger(f"carfind.{role}")
    if getattr(logger, "_carfind_ready", False):
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        ensure_log_dir()
        handler = RotatingFileHandler(
            log_path(role),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)-7s [%(process)d] %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    _enable_faulthandler(role)
    logger._carfind_ready = True  # type: ignore[attr-defined]
    logger.info("===== %s process started, CarFind %s, pid=%d =====", role, VERSION, os.getpid())
    return logger


def _enable_faulthandler(role: str) -> None:
    try:
        f = open(LOG_DIR / f"crash-{role}.log", "a", encoding="utf-8", buffering=1)
        f.write(
            f"\n===== {role} pid={os.getpid()} started "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} (only fatal native errors are written below) =====\n"
        )
        faulthandler.enable(file=f, all_threads=True)
        _fault_files.append(f)
    except (OSError, ValueError):
        pass


def install_excepthooks(logger: logging.Logger) -> None:
    def _hook(exc_type, exc, tb) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    def _thread_hook(args) -> None:
        logger.critical(
            "Unhandled exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def log_environment(logger: logging.Logger) -> None:
    logger.info(
        "frozen=%s exe=%s root=%s",
        bool(getattr(sys, "frozen", False)),
        sys.executable,
        ROOT,
    )
    logger.info("python=%s os=%s machine=%s", sys.version.split()[0], platform.platform(), platform.machine())
    try:
        import psutil

        vm = psutil.virtual_memory()
        freq = psutil.cpu_freq()
        logger.info(
            "cpu=%s logical=%s physical=%s freq=%sMHz ram_total=%.1fGB ram_free=%.1fGB",
            platform.processor(),
            psutil.cpu_count(logical=True),
            psutil.cpu_count(logical=False),
            int(freq.max) if freq and freq.max else "?",
            vm.total / 1024**3,
            vm.available / 1024**3,
        )
    except Exception as exc:  # pragma: no cover - psutil optional at runtime
        logger.info("cpu=%s logical=%s (psutil unavailable: %s)", platform.processor(), os.cpu_count(), exc)


def _gui_resources(pid: int, kind: int) -> int:
    try:
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        handle = k32.OpenProcess(0x0400, False, pid)
        if not handle:
            return -1
        try:
            return int(u32.GetGuiResources(handle, kind))
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return -1


def sample_process(pid: int | None) -> str:
    """One-line resource snapshot of a process (cpu% is since the previous sample)."""
    if pid is None:
        return "n/a"
    try:
        import psutil

        proc = _procs.get(pid)
        if proc is None:
            proc = psutil.Process(pid)
            proc.cpu_percent(None)
            _procs[pid] = proc
        mem = proc.memory_info()
        private = getattr(mem, "private", 0)
        return (
            f"pid={pid} cpu={proc.cpu_percent(None):.0f}% rss={mem.rss / 1048576:.0f}MB "
            f"private={private / 1048576:.0f}MB threads={proc.num_threads()} "
            f"handles={proc.num_handles()} gdi={_gui_resources(pid, 0)} user={_gui_resources(pid, 1)}"
        )
    except Exception as exc:
        return f"pid={pid} unavailable ({exc.__class__.__name__}: {exc})"


def system_load() -> str:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return f"sys_cpu={psutil.cpu_percent(None):.0f}% ram_used={vm.percent:.0f}% ram_free={vm.available / 1024**3:.1f}GB"
    except Exception:
        return "sys n/a"


def settings_summary(settings) -> str:
    """Settings without DingTalk secrets."""
    keys = (
        "interval_sec",
        "show_labels",
        "debug_mode",
        "parking_conf",
        "intrusion_conf",
        "intrusion_alert",
        "parking_alert",
        "congestion_alert",
        "congestion_count",
        "voice_alert",
        "auto_open_image",
        "gaze_guidance",
        "cooldown_sec",
        "parking_hold_sec",
        "parking_grace_frames",
        "ding_alert",
        "worker_threads",
        "worker_cpu_affinity",
    )
    parts = [f"{key}={getattr(settings, key, '?')}" for key in keys]
    parts.append(f"ding_webhook_set={bool(getattr(settings, 'ding_webhook', ''))}")
    parts.append(f"ding_app_set={bool(getattr(settings, 'ding_app_key', ''))}")
    return " ".join(parts)
