"""Project-local paths."""

from __future__ import annotations

import sys
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
PIC_DIR = ROOT / "Pic"
FALSE_POSITIVE_DIR = PIC_DIR / "FalsePositive"
DOWNLOAD_DIR = ROOT / "Download"
WARNING_DIR = ROOT / "warning"
INTRUSION_WAV = WARNING_DIR / "Pwarning.wav"
PARKING_WAV = WARNING_DIR / "Vwarning.wav"
CONGESTION_WAV = WARNING_DIR / "Bwarning.wav"
READY_WAV = WARNING_DIR / "Rwarning.wav"
WEIGHTS_NAME = "yolo26l.pt"
WEIGHTS_FILE = DOWNLOAD_DIR / WEIGHTS_NAME
CONFIG_FILE = ROOT / "config.json"
YOLO_HOME = DOWNLOAD_DIR / "ultralytics"
LOG_DIR = ROOT / "logs"

WEIGHTS_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt"
WEIGHTS_MIN_BYTES = 40_000_000


def ensure_pic_dir() -> Path:
    PIC_DIR.mkdir(parents=True, exist_ok=True)
    ensure_false_positive_dir()
    return PIC_DIR


def ensure_false_positive_dir() -> Path:
    FALSE_POSITIVE_DIR.mkdir(parents=True, exist_ok=True)
    return FALSE_POSITIVE_DIR


def ensure_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def ensure_download_dir() -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    YOLO_HOME.mkdir(parents=True, exist_ok=True)
    return DOWNLOAD_DIR
