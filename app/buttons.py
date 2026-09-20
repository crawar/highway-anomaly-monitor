"""Circular metallic buttons with 3D press feedback."""

from __future__ import annotations

import time
from math import cos, pi

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app import icons
from app import theme as T


class MetalButton(QWidget):
    clicked = Signal()
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(T.BTN_SIZE, T.BTN_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._press = 0.0
        self._hover = 0.0
        self._face_opacity = 1.0
        self._toggled = False
        self._breath = 0.0
        self._gear_rot = 0.0
        self._fold = 0.0
        self._hovered = False
        self._pressed = False
        self._interactive = True
        self._press_at: QPoint | None = None
        self._dragged = False

        self._press_anim = QPropertyAnimation(self, b"press", self)
        self._press_anim.setDuration(T.PRESS_MS)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hover_anim = QPropertyAnimation(self, b"hover", self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Breathing runs on a coarse timer (10 fps) rather than a 60 fps
        # QPropertyAnimation: the HUD is a layered window, so every repaint is
        # an UpdateLayeredWindow the compositor must absorb for the whole run.
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(T.BREATH_TICK_MS)
        self._breath_timer.timeout.connect(self._on_breath_tick)
        self._breath_t0 = 0.0
        self._breath_paused = False

        self._gear_anim = QPropertyAnimation(self, b"gear_rot", self)
        self._gear_anim.setDuration(T.GEAR_SPIN_MS)
        self._gear_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._gear_anim.finished.connect(self._on_gear_finished)

    def get_press(self) -> float:
        return self._press

    def set_press(self, value: float) -> None:
        self._press = value
        self.update()

    press = Property(float, get_press, set_press)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    hover = Property(float, get_hover, set_hover)

    def _on_breath_tick(self) -> None:
        phase = ((time.monotonic() - self._breath_t0) * 1000.0 % T.BREATH_MS) / T.BREATH_MS
        # 0 -> 1 -> 0 over one period, same ease-in/out shape as before.
        self._breath = 0.5 - 0.5 * cos(2.0 * pi * phase)
        self.update()

    def _sync_breath(self) -> None:
        want = self._toggled and self.kind in ("play", "select") and not self._breath_paused
        if want:
            if not self._breath_timer.isActive():
                self._breath_t0 = time.monotonic()
                self._breath_timer.start()
            return
        if self._breath_timer.isActive():
            self._breath_timer.stop()
        if self._breath != 0.0:
            self._breath = 0.0
            self.update()

    def set_breath_paused(self, paused: bool) -> None:
        """Freeze the breathing icon (e.g. while the capsule is collapsed)."""
        paused = bool(paused)
        if paused == self._breath_paused:
            return
        self._breath_paused = paused
        self._sync_breath()

    def get_gear_rot(self) -> float:
        return self._gear_rot

    def set_gear_rot(self, value: float) -> None:
        self._gear_rot = value
        self.update()

    gear_rot = Property(float, get_gear_rot, set_gear_rot)

    def set_face_opacity(self, value: float) -> None:
        self._face_opacity = max(0.0, min(1.0, value))
        visible = self._face_opacity > 0.02
        self.setVisible(visible)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._face_opacity < 0.45,
        )
        self.update()

    def set_fold(self, value: float) -> None:
        self._fold = value
        self.update()

    def is_toggled(self) -> bool:
        return self._toggled

    def is_interactive(self) -> bool:
        return self._interactive

    def set_interactive(self, on: bool) -> None:
        self._interactive = bool(on)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._interactive else Qt.CursorShape.ArrowCursor
        )
        if not self._interactive:
            self._pressed = False
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._hover)
            self._hover_anim.setEndValue(0.0)
            self._hover_anim.start()
            if self.kind == "settings":
                self._gear_anim.stop()
                rest = round(self._gear_rot / 45.0) * 45.0
                self._gear_anim.setStartValue(self._gear_rot)
                self._gear_anim.setEndValue(rest)
                self._gear_anim.setDuration(280)
                self._gear_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._gear_anim.start()
        self.update()

    def set_toggled(self, on: bool) -> None:
        self._toggled = on
        self._sync_breath()
        self.update()

    def _on_gear_finished(self) -> None:
        if self.kind == "settings" and self._hovered and self._interactive:
            self._gear_anim.setStartValue(self._gear_rot)
            self._gear_anim.setEndValue(self._gear_rot + 180.0)
            self._gear_anim.setDuration(T.GEAR_SPIN_MS)
            self._gear_anim.setEasingCurve(QEasingCurve.Type.Linear)
            self._gear_anim.start()

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self.hover_entered.emit()
        if self._interactive:
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._hover)
            self._hover_anim.setEndValue(1.0)
            self._hover_anim.start()
            if self.kind == "settings":
                self._gear_anim.stop()
                self._gear_anim.setStartValue(self._gear_rot)
                self._gear_anim.setEndValue(self._gear_rot + 180.0)
                self._gear_anim.setDuration(T.GEAR_SPIN_MS)
                self._gear_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
                self._gear_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._pressed = False
        self.hover_left.emit()
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        if self.kind == "settings":
            self._gear_anim.stop()
            rest = round(self._gear_rot / 45.0) * 45.0
            self._gear_anim.setStartValue(self._gear_rot)
            self._gear_anim.setEndValue(rest)
            self._gear_anim.setDuration(280)
            self._gear_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._gear_anim.start()
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "show_exit_popup"):
            parent.show_exit_popup(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.globalPosition().toPoint()
            self._dragged = False
            if self._interactive:
                self._pressed = True
                self._press_anim.stop()
                self._press_anim.setStartValue(self._press)
                self._press_anim.setEndValue(1.0)
                self._press_anim.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._press_at is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            now = event.globalPosition().toPoint()
            if not self._dragged and (now - self._press_at).manhattanLength() >= 8:
                self._dragged = True
                self._pressed = False
                self._press_anim.stop()
                self._press_anim.setStartValue(self._press)
                self._press_anim.setEndValue(0.0)
                self._press_anim.start()
                parent = self.parent()
                if parent is not None and hasattr(parent, "start_window_drag"):
                    parent.start_window_drag(self._press_at)
            if self._dragged:
                parent = self.parent()
                if parent is not None and hasattr(parent, "drag_window_to"):
                    parent.drag_window_to(now)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_pressed = self._pressed
            dragged = self._dragged
            self._pressed = False
            self._press_at = None
            self._dragged = False
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
            parent = self.parent()
            if dragged:
                if parent is not None and hasattr(parent, "end_window_drag"):
                    parent.end_window_drag()
                event.accept()
                return
            if (
                self._interactive
                and was_pressed
                and self.rect().contains(event.position().toPoint())
            ):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(self._face_opacity)

        d = self.width()
        rect = QRectF(0.5, 0.5, d - 1.0, d - 1.0)
        k = self._press
        hov = self._hover
        sink = 1.15 * k

        # Drop shadow (lifts when idle, flattens when pressed)
        shadow = QColor(0, 0, 0, int(70 * (1.0 - k) + 18))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(rect.adjusted(1.2, 1.8 + 1.2 * (1 - k), -1.2, 1.6 - sink))

        face = rect.adjusted(1.0, 1.0 + sink, -1.0, -1.0 + sink)

        # Outer metal rim
        rim = QRadialGradient(face.center().x() - face.width() * 0.22, face.center().y() - face.height() * 0.30, face.width() * 0.78)
        if k > 0.5:
            rim.setColorAt(0.0, QColor(48, 52, 58))
            rim.setColorAt(0.55, QColor(28, 30, 34))
            rim.setColorAt(1.0, QColor(96, 102, 110))
        else:
            light = 138 + int(28 * hov)
            rim.setColorAt(0.0, QColor(light, light + 4, light + 10))
            rim.setColorAt(0.38, T.BTN_MID)
            rim.setColorAt(0.78, T.BTN_DARK)
            rim.setColorAt(1.0, QColor(10, 11, 12))
        p.setBrush(rim)
        p.drawEllipse(face)

        # Inner basin
        inner = face.adjusted(2.1, 2.1, -2.1, -2.1)
        basin = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        if k > 0.4:
            basin.setColorAt(0.0, QColor(18, 19, 22))
            basin.setColorAt(0.45, QColor(36, 39, 44))
            basin.setColorAt(1.0, QColor(58, 62, 68))
        else:
            basin.setColorAt(0.0, QColor(86 + int(18 * hov), 90 + int(18 * hov), 96 + int(16 * hov)))
            basin.setColorAt(0.42, QColor(48, 52, 57))
            basin.setColorAt(1.0, QColor(24, 26, 30))
        p.setBrush(basin)
        p.drawEllipse(inner)

        # Specular highlight
        gloss = QRectF(inner)
        gloss.setHeight(inner.height() * 0.46)
        gloss.moveTop(inner.top() + 0.6 + sink * 0.2)
        gloss_path = QPainterPath()
        gloss_path.addEllipse(inner)
        p.save()
        p.setClipPath(gloss_path)
        gg = QLinearGradient(gloss.topLeft(), gloss.bottomLeft())
        gg.setColorAt(0.0, QColor(255, 255, 255, int(78 * (1.0 - 0.55 * k) + 18 * hov)))
        gg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(gg)
        p.drawEllipse(gloss)
        p.restore()

        # Fine rim line
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(230, 235, 240, int(40 + 35 * hov * (1 - k))), 1.0))
        p.drawEllipse(face.adjusted(0.6, 0.6, -0.6, -0.6))

        self._paint_icon(p, inner)

        if not self._interactive:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(T.DISABLED_VEIL)
            p.drawEllipse(face)

    def _paint_icon(self, p: QPainter, inner: QRectF) -> None:
        if self.kind == "play":
            if self._toggled:
                icons.draw_stop_square(p, inner, self._breath)
            else:
                icons.draw_play_triangle(p, inner)
        elif self.kind == "select":
            if self._toggled:
                pulse = 0.45 + 0.55 * self._breath
                icons.draw_dashed_square(p, inner, T.ICON_YELLOW, pulse)
            else:
                icons.draw_dashed_square(p, inner, T.ICON_WHITE, 1.0)
        elif self.kind == "list":
            icons.draw_folder(p, inner)
        elif self.kind == "settings":
            icons.draw_gear(p, inner, self._gear_rot)
        elif self.kind == "collapse":
            icons.draw_collapse_chevrons(p, inner, self._fold)
