"""Metallic HUD chrome: tooltip and right-click exit popup."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from app import VERSION, theme as T
from app.win32util import apply_capture_affinity


def _ui_font(pixel_size: int) -> QFont:
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    font.setPixelSize(pixel_size)
    return font


def _paint_metal_panel(p: QPainter, body: QRectF, radius: float | None = None) -> None:
    if radius is None:
        radius = min(body.height() / 2.0, 14.0)
    clip = QPainterPath()
    clip.addRoundedRect(body, radius, radius)

    metal = QLinearGradient(body.topLeft(), body.bottomLeft())
    metal.setColorAt(0.00, T.WINDOW_TOP)
    metal.setColorAt(0.18, QColor(44, 47, 53))
    metal.setColorAt(0.50, T.WINDOW_MID)
    metal.setColorAt(0.82, QColor(20, 22, 25))
    metal.setColorAt(1.00, T.WINDOW_BOT)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(metal)
    p.drawRoundedRect(body, radius, radius)

    p.setOpacity(0.07)
    band = QLinearGradient(body.topLeft(), body.topRight())
    band.setColorAt(0.0, QColor(0, 0, 0, 0))
    band.setColorAt(0.35, QColor(255, 255, 255, 80))
    band.setColorAt(0.7, QColor(0, 0, 0, 40))
    band.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(band)
    p.drawRoundedRect(body, radius, radius)
    p.setOpacity(1.0)

    sheen = QLinearGradient(body.x(), body.y(), body.x(), body.y() + body.height() * 0.55)
    sheen.setColorAt(0.0, T.WINDOW_SHEEN)
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(sheen)
    p.drawRoundedRect(
        QRectF(body.x(), body.y(), body.width(), body.height() * 0.55),
        radius,
        radius,
    )

    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(T.WINDOW_RIM, 1.15))
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _paint_metal_capsule(p: QPainter, body: QRectF) -> None:
    _paint_metal_panel(p, body, body.height() / 2.0)


def _clamp_to_screen(pos: QPoint, size_w: int, size_h: int) -> QPoint:
    screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
    geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 800, 600)
    x = min(max(pos.x(), geo.x() + 4), geo.right() - size_w - 4)
    y = min(max(pos.y(), geo.y() + 4), geo.bottom() - size_h - 4)
    return QPoint(x, y)


def place_above_rect(anchor: QRect, size_w: int, size_h: int, gap: int = 8) -> QPoint:
    screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
    geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 800, 600)
    x = anchor.center().x() - size_w // 2
    x = min(max(x, geo.x() + 4), geo.right() - size_w - 4)
    y_above = anchor.top() - size_h - gap
    if y_above >= geo.y() + 4:
        return QPoint(x, y_above)
    y_below = anchor.bottom() + gap
    if y_below + size_h <= geo.bottom() - 4:
        return QPoint(x, y_below)
    y = min(max(y_above, geo.y() + 4), geo.bottom() - size_h - 4)
    return QPoint(x, y)


class MetalTip(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self.setFont(_ui_font(12))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_capture_affinity(self)

    def popup(self, text: str, anchor: QRect) -> None:
        self._text = text
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(text) + 22
        h = fm.height() + 12
        self.setFixedSize(w, h)

        x = anchor.center().x() - w // 2
        y = anchor.top() - h - 8
        if y < 4:
            y = anchor.bottom() + 8
        pos = _clamp_to_screen(QPoint(x, y), w, h)
        self.move(pos)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_capsule(p, body)
        p.setPen(T.TIP_TEXT)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class AboutPopup(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(_ui_font(13))
        self._title = "湖南交警总队@2026 高速交管六支队人工智能开发小组"
        self._version = f"CarFind {VERSION}"
        fm = self.fontMetrics()
        width = max(fm.horizontalAdvance(self._title), fm.horizontalAdvance(self._version)) + 36
        height = fm.height() * 2 + 28
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_capture_affinity(self)

    def popup_at(self, global_pos: QPoint) -> None:
        pos = _clamp_to_screen(global_pos, self.width(), self.height())
        self.move(pos)
        self.show()
        self.raise_()

    def popup_above(self, home: QRect) -> None:
        pos = place_above_rect(home, self.width(), self.height())
        self.move(pos)
        self.show()
        self.raise_()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 14.0)
        p.setPen(T.POPUP_TEXT)
        p.setFont(self.font())
        line = self.fontMetrics().height() + 4
        p.drawText(
            QRect(0, 8, self.width(), line),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._title,
        )
        p.setPen(T.SETTINGS_MUTED)
        p.drawText(
            QRect(0, 8 + line, self.width(), line),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._version,
        )


class ExitPopup(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(96, 76)
        self.setFont(_ui_font(12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover = ""
        self._about = AboutPopup(parent)
        self._home_rect = QRect()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_capture_affinity(self)

    def popup_at(self, global_pos: QPoint, home: QRect | None = None) -> None:
        pos = _clamp_to_screen(global_pos, self.width(), self.height())
        self.move(pos)
        self._hover = ""
        if home is not None and not home.isEmpty():
            self._home_rect = QRect(home)
        else:
            self._home_rect = QRect(pos, self.size())
        self.show()
        self.raise_()

    def _item_rect(self, kind: str) -> QRect:
        if kind == "about":
            return QRect(8, 8, self.width() - 16, 28)
        return QRect(8, 40, self.width() - 16, 28)

    def _hit(self, pos: QPoint) -> str:
        if self._item_rect("about").contains(pos):
            return "about"
        if self._item_rect("quit").contains(pos):
            return "quit"
        return ""

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hover = self._hit(event.position().toPoint())
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = ""
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            kind = self._hit(event.position().toPoint())
            if kind == "about":
                home = QRect(self._home_rect)
                self.close()
                QTimer.singleShot(0, lambda: self._about.popup_above(home))
                event.accept()
                return
            if kind == "quit":
                self.close()
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 12.0)
        p.setFont(self.font())
        for kind, title in (("about", "关于"), ("quit", "退出")):
            rect = self._item_rect(kind)
            if self._hover == kind:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.POPUP_HOVER)
                p.drawRoundedRect(QRectF(rect), 8.0, 8.0)
            p.setPen(T.POPUP_TEXT)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)
