"""Persisted HUD settings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app import theme as T
from app.detect import DEFAULT_WORKER_THREADS, WORKER_THREADS_MAX, WORKER_THREADS_MIN
from app.paths import CONFIG_FILE


def snap_interval(value: float) -> float:
    steps = T.INTERVAL_STEPS
    return min(steps, key=lambda step: abs(step - float(value)))


def snap_cooldown(value: float) -> int:
    steps = T.COOLDOWN_STEPS
    return int(min(steps, key=lambda step: abs(step - float(value))))


def snap_congestion_count(value: float) -> int:
    steps = T.CONGESTION_COUNT_STEPS
    return int(min(steps, key=lambda step: abs(step - float(value))))


def _debug_mode_from(data: dict[str, Any]) -> bool:
    if "debug_mode" in data:
        return bool(data.get("debug_mode"))
    if "hide_low_conf" in data:
        return not bool(data.get("hide_low_conf"))
    return False


@dataclass
class AppSettings:
    interval_sec: float = T.DEFAULT_INTERVAL
    show_labels: bool = True
    debug_mode: bool = False
    parking_conf: float = T.DEFAULT_CONF
    intrusion_conf: float = T.DEFAULT_INTRUSION_CONF
    intrusion_alert: bool = True
    parking_alert: bool = True
    congestion_alert: bool = True
    congestion_count: int = T.DEFAULT_CONGESTION_COUNT
    voice_alert: bool = True
    auto_open_image: bool = True
    gaze_guidance: bool = True
    cooldown_sec: int = T.DEFAULT_COOLDOWN
    parking_hold_sec: int = T.DEFAULT_PARKING_HOLD
    parking_grace_frames: int = T.DEFAULT_PARKING_GRACE
    ding_alert: bool = False
    ding_keyword: str = ""
    ding_secret: str = ""
    ding_webhook: str = ""
    ding_app_key: str = ""
    ding_app_secret: str = ""
    # Detector process: torch intra-op threads, and an optional logical-CPU
    # list such as "16-23" (e.g. the E-cores of an i7-13700K). Empty = all CPUs.
    worker_threads: int = DEFAULT_WORKER_THREADS
    worker_cpu_affinity: str = ""

    def clamp(self) -> AppSettings:
        self.interval_sec = snap_interval(self.interval_sec)
        self.show_labels = bool(self.show_labels)
        self.debug_mode = bool(self.debug_mode)
        self.parking_conf = min(0.95, max(0.05, float(self.parking_conf)))
        self.intrusion_conf = min(0.95, max(0.05, float(self.intrusion_conf)))
        self.intrusion_alert = bool(self.intrusion_alert)
        self.parking_alert = bool(self.parking_alert)
        self.congestion_alert = bool(self.congestion_alert)
        self.congestion_count = snap_congestion_count(self.congestion_count)
        self.voice_alert = bool(self.voice_alert)
        self.auto_open_image = bool(self.auto_open_image)
        self.gaze_guidance = bool(self.gaze_guidance)
        self.ding_alert = bool(self.ding_alert)
        self.ding_keyword = str(self.ding_keyword or "").strip()
        self.ding_secret = str(self.ding_secret or "").strip()
        self.ding_webhook = str(self.ding_webhook or "").strip()
        self.ding_app_key = str(self.ding_app_key or "").strip()
        self.ding_app_secret = str(self.ding_app_secret or "").strip()
        self.cooldown_sec = snap_cooldown(self.cooldown_sec)
        self.parking_hold_sec = int(
            min(
                T.PARKING_HOLD_MAX,
                max(T.PARKING_HOLD_MIN, round(float(self.parking_hold_sec))),
            )
        )
        self.parking_grace_frames = int(
            min(
                T.PARKING_GRACE_MAX,
                max(T.PARKING_GRACE_MIN, round(float(self.parking_grace_frames))),
            )
        )
        try:
            threads = int(round(float(self.worker_threads)))
        except (TypeError, ValueError):
            threads = DEFAULT_WORKER_THREADS
        self.worker_threads = min(WORKER_THREADS_MAX, max(WORKER_THREADS_MIN, threads))
        self.worker_cpu_affinity = str(self.worker_cpu_affinity or "").strip()
        return self


def _from_dict(data: dict[str, Any]) -> AppSettings:
    return AppSettings(
        interval_sec=data.get("interval_sec", T.DEFAULT_INTERVAL),
        show_labels=data.get("show_labels", True),
        debug_mode=_debug_mode_from(data),
        parking_conf=data.get("parking_conf", T.DEFAULT_CONF),
        intrusion_conf=data.get("intrusion_conf", T.DEFAULT_INTRUSION_CONF),
        intrusion_alert=data.get("intrusion_alert", True),
        parking_alert=data.get("parking_alert", True),
        congestion_alert=data.get("congestion_alert", True),
        congestion_count=data.get("congestion_count", T.DEFAULT_CONGESTION_COUNT),
        voice_alert=data.get("voice_alert", True),
        auto_open_image=data.get("auto_open_image", True),
        gaze_guidance=data.get("gaze_guidance", True),
        cooldown_sec=data.get("cooldown_sec", T.DEFAULT_COOLDOWN),
        parking_hold_sec=data.get("parking_hold_sec", T.DEFAULT_PARKING_HOLD),
        parking_grace_frames=data.get("parking_grace_frames", T.DEFAULT_PARKING_GRACE),
        ding_alert=data.get("ding_alert", False),
        ding_keyword=data.get("ding_keyword", ""),
        ding_secret=data.get("ding_secret", ""),
        ding_webhook=data.get("ding_webhook", ""),
        ding_app_key=data.get("ding_app_key", ""),
        ding_app_secret=data.get("ding_app_secret", ""),
        worker_threads=data.get("worker_threads", DEFAULT_WORKER_THREADS),
        worker_cpu_affinity=data.get("worker_cpu_affinity", ""),
    ).clamp()


def load_settings() -> AppSettings:
    if not CONFIG_FILE.is_file():
        return AppSettings()
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    settings.clamp()
    CONFIG_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
