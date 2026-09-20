# -*- mode: python ; coding: utf-8 -*-
import re
from math import pi, sin
from pathlib import Path

from PIL import Image, ImageDraw
from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPECPATH)


def _app_version() -> str:
    """Read VERSION from app/__init__.py so the output folder is CarFind-<version>."""
    text = (SPECDIR / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("VERSION not found in app/__init__.py")
    return match.group(1)


APP_VERSION = _app_version()


def _build_app_icon() -> Path:
    """Create the Windows icon used by the packaged executable."""
    target = SPECDIR / "build" / "carfind.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((24, 24, 232, 232), fill=(115, 199, 242, 255))

    upper = []
    lower = []
    for index in range(65):
        t = index / 64
        x = 66 + 124 * t
        curve = 40 * sin(pi * t)
        upper.append((round(x), round(128 - curve)))
        lower.append((round(x), round(128 + curve)))
    eye = upper + list(reversed(lower)) + [upper[0]]
    draw.line(eye, fill=(255, 255, 255, 255), width=14, joint="curve")
    draw.ellipse((110, 110, 146, 146), fill=(255, 255, 255, 255))
    image.save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return target


APP_ICON = _build_app_icon()


def _gather(packages):
    datas, binaries, hidden = [], [], []
    for name in packages:
        d, b, h = collect_all(name)
        datas += d
        binaries += b
        hidden += h
    return datas, binaries, hidden


datas, binaries, hiddenimports = _gather(
    (
        "torch",
        "torchvision",
        "ultralytics",
        "cv2",
        "mss",
    )
)

hiddenimports += collect_submodules("app")
hiddenimports += [
    "multiprocessing",
    "numpy",
    "PIL",
    "yaml",
    "requests",
    "psutil",
    "matplotlib",
    "polars",
    "app.detect.worker",
    "app.detect.parking",
    "app.detect.intrusion",
]

excludes = [
    "tkinter",
    "IPython",
    "notebook",
    "pytest",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtQuick3D",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
]

a = Analysis(
    [str(SPECDIR / "app" / "main.py")],
    pathex=[str(SPECDIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CarFind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=f"CarFind-{APP_VERSION}",
)
