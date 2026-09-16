"""Fullscreen transparent rectangle picker.

The overlay must not replace or dim the desktop: only the rubber-band
border is painted. A 1-alpha fill keeps the window hittable on Windows
layered surfaces without a visible veil.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app import theme as T
from app.win32util import apply_capture_affinity


def virtual_desktop() -> QRect:
    virt = QRect()
    for screen in QGuiApplication.screens():
        virt = virt.united(screen.geometry())
    return virt


class RegionPicker(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, virt: QRect) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setWindowTitle("CarFind Region")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(virt)

        self._virt = QRect(virt)
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._chosen: QRect | None = None
        self._blink_on = True
        self._blink_ticks = 0
        self._done = False

        self._blink = QTimer(self)
        self._blink.setInterval(T.PICK_BLINK_MS)
        self._blink.timeout.connect(self._on_blink)

    def _selection(self) -> QRect | None:
        if self._chosen is not None:
            return QRect(self._chosen)
        if not self._dragging:
            return None
        return QRect(self._origin, self._current).normalized()

    def _commit(self, rect: QRect) -> None:
        self._chosen = QRect(rect)
        self._dragging = False
        self._blink_on = True
        self._blink_ticks = 0
        self._blink.start()
        self.update()

    def _finish_selected(self) -> None:
        if self._done or self._chosen is None:
            return
        self._done = True
        self._blink.stop()
        global_rect = QRect(self._chosen)
        global_rect.translate(self._virt.topLeft())
        self.selected.emit(global_rect)
        self.close()

    def _cancel(self) -> None:
        if self._done:
            return
        if self._chosen is not None:
            self._finish_selected()
            return
        self._done = True
        self._blink.stop()
        self.cancelled.emit()
        self.close()

    def _on_blink(self) -> None:
        self._blink_ticks += 1
        if self._blink_ticks >= T.PICK_BLINK_TICKS:
            self._finish_selected()
            return
        self._blink_on = not self._blink_on
        self.update()

    def _arm_input(self) -> None:
        if self._done or not self.isVisible():
            return
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_capture_affinity(self)
        QTimer.singleShot(0, self._arm_input)

    def closeEvent(self, event) -> None:
        self.releaseKeyboard()
        if not self._done:
            self._done = True
            self._blink.stop()
            if self._chosen is not None:
                global_rect = QRect(self._chosen)
                global_rect.translate(self._virt.topLeft())
                self.selected.emit(global_rect)
            else:
                self.cancelled.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._chosen is not None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._chosen is None:
            self._current = event.position().toPoint()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging and self._chosen is None:
            self._dragging = False
            rect = QRect(self._origin, event.position().toPoint()).normalized()
            if rect.width() >= T.MIN_REGION and rect.height() >= T.MIN_REGION:
                self._commit(rect)
            else:
                self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Alpha 1 is invisible but not click-through on a layered window.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))

        sel = self._selection()
        if sel is None or sel.width() <= 0 or sel.height() <= 0:
            return
        if self._chosen is not None and not self._blink_on:
            return
        outer = QPen(T.PICK_BORDER, 2.4)
        outer.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(outer)
        p.drawRect(sel.adjusted(1, 1, -1, -1))
        inner = QPen(T.PICK_BORDER_INNER, 1.0)
        p.setPen(inner)
        p.drawRect(sel.adjusted(3, 3, -3, -3))
