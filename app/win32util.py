"""Windows helpers for layered overlay windows."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator

from PySide6.QtWidgets import QApplication, QWidget

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1

_demo_capture = False


def _hwnd(widget: QWidget) -> int:
    return int(widget.winId())


def disable_system_rounding(widget: QWidget) -> None:
    try:
        value = wintypes.DWORD(DWMWCP_DONOTROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            _hwnd(widget),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        pass


def set_demo_capture(allowed: bool) -> None:
    global _demo_capture
    _demo_capture = bool(allowed)


def demo_capture_allowed() -> bool:
    return _demo_capture


def set_capture_allowed(widget: QWidget, allowed: bool) -> None:
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(
            _hwnd(widget),
            WDA_NONE if allowed else WDA_EXCLUDEFROMCAPTURE,
        )
    except Exception:
        pass


def apply_capture_affinity(widget: QWidget) -> None:
    set_capture_allowed(widget, _demo_capture)


def exclude_from_capture(widget: QWidget) -> None:
    set_capture_allowed(widget, False)


@contextmanager
def capture_hidden(*widgets: QWidget | None) -> Iterator[None]:
    alive = [widget for widget in widgets if widget is not None]
    for widget in alive:
        set_capture_allowed(widget, False)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    try:
        yield
    finally:
        for widget in alive:
            apply_capture_affinity(widget)
        if app is not None:
            app.processEvents()


def enable_click_through(widget: QWidget) -> None:
    try:
        hwnd = _hwnd(widget)
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )
    except Exception:
        pass
