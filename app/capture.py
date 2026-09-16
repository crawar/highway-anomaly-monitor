"""Capture a Qt logical rectangle from the live desktop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

try:
    import mss
except ImportError:  # pragma: no cover
    mss = None


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
)


def _enum_monitors() -> list[MONITORINFOEXW]:
    found: list[MONITORINFOEXW] = []

    def _callback(hmon, _hdc, _lprect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found.append(info)
        return 1

    cb = MonitorEnumProc(_callback)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, None)
    return found


def _physical_monitor(screen) -> wintypes.RECT | None:
    name = str(screen.name() or "")
    dpr = float(screen.devicePixelRatio())
    geo = screen.geometry()
    want_w = max(1, int(round(geo.width() * dpr)))
    want_h = max(1, int(round(geo.height() * dpr)))
    named = None
    sized = None
    for info in _enum_monitors():
        mon = info.rcMonitor
        phys_w = mon.right - mon.left
        phys_h = mon.bottom - mon.top
        if name and info.szDevice == name:
            named = mon
        if phys_w == want_w and phys_h == want_h:
            sized = mon
    return named or sized


def qrect_to_physical(rect: QRect) -> dict[str, int]:
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return {
            "left": rect.x(),
            "top": rect.y(),
            "width": max(2, rect.width()),
            "height": max(2, rect.height()),
        }
    geo = screen.geometry()
    dpr = float(screen.devicePixelRatio())
    mon = _physical_monitor(screen)
    if mon is None:
        return {
            "left": int(round(rect.x() * dpr)),
            "top": int(round(rect.y() * dpr)),
            "width": max(2, int(round(rect.width() * dpr))),
            "height": max(2, int(round(rect.height() * dpr))),
        }
    phys_w = max(1, mon.right - mon.left)
    phys_h = max(1, mon.bottom - mon.top)
    sx = phys_w / max(1, geo.width())
    sy = phys_h / max(1, geo.height())
    left = mon.left + int(round((rect.x() - geo.x()) * sx))
    top = mon.top + int(round((rect.y() - geo.y()) * sy))
    width = max(2, int(round(rect.width() * sx)))
    height = max(2, int(round(rect.height() * sy)))
    return {"left": left, "top": top, "width": width, "height": height}


class ScreenGrabber:
    def __init__(self) -> None:
        self._sct = mss.mss() if mss is not None else None

    def grab(self, rect: QRect):
        import numpy as np

        if rect.width() < 2 or rect.height() < 2:
            return None
        if self._sct is not None:
            try:
                raw = self._sct.grab(qrect_to_physical(rect))
                arr = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(
                    raw.height, raw.width, 4
                )
                return np.ascontiguousarray(arr[:, :, :3])
            except Exception:
                pass
        return self._grab_qt(rect)

    def _grab_qt(self, rect: QRect):
        import numpy as np
        from PySide6.QtGui import QImage

        screen = QGuiApplication.screenAt(QPoint(rect.center())) or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        geo = screen.geometry()
        pixmap = screen.grabWindow(
            0,
            rect.x() - geo.x(),
            rect.y() - geo.y(),
            rect.width(),
            rect.height(),
        )
        if pixmap.isNull():
            return None
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        w = image.width()
        h = image.height()
        ptr = image.bits()
        buf = bytes(ptr) if not isinstance(ptr, (bytes, bytearray)) else ptr
        arr = np.frombuffer(buf, dtype=np.uint8)
        stride = image.bytesPerLine()
        if stride != w * 3:
            rows = [arr[i * stride : i * stride + w * 3] for i in range(h)]
            rgb = np.ascontiguousarray(np.stack(rows).reshape(h, w, 3))
            return np.ascontiguousarray(rgb[:, :, ::-1])
        rgb = arr.reshape(h, w, 3).copy()
        return np.ascontiguousarray(rgb[:, :, ::-1])

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
