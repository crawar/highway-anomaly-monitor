"""Transparent AR overlay for detector boxes and region edge."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from app import theme as T
from app.config import AppSettings
from app.detect import LABELS_ZH
from app.hud import _ui_font
from app.win32util import apply_capture_affinity, disable_system_rounding, enable_click_through


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowTitle("CarFind Overlay")
        self._parking: list[dict] = []
        self._intrusion: list[dict] = []
        self._alert_ids: set[int] = set()
        self._image_size = (1, 1)
        self._settings = AppSettings()
        self._chrome_ready = False
        self._alerting = False
        self._region_on = True
        self.setFont(_ui_font(11))

        self._blink = QTimer(self)
        self._blink.setInterval(T.ALERT_BLINK_MS)
        self._blink.timeout.connect(self._on_blink)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            enable_click_through(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def set_region(self, rect: QRect) -> None:
        if rect.width() < 2 or rect.height() < 2:
            self.hide()
            return
        self.setGeometry(rect)

    def set_alerting(self, alerting: bool) -> None:
        self._alerting = bool(alerting)
        self._region_on = True
        if self._alerting:
            if not self._blink.isActive():
                self._blink.start()
        else:
            self._blink.stop()
        self.update()

    def set_scene(
        self,
        parking: list[dict],
        intrusion: list[dict],
        image_size: tuple[int, int],
        settings: AppSettings,
        alert_items: list[dict] | None = None,
    ) -> None:
        self._parking = list(parking)
        self._intrusion = list(intrusion)
        self._alert_ids = {id(item) for item in (alert_items or [])}
        self._image_size = (max(1, int(image_size[0])), max(1, int(image_size[1])))
        self.apply_settings(settings)

    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        if self._chrome_ready:
            apply_capture_affinity(self)
        self.update()

    def clear_scene(self) -> None:
        self._parking = []
        self._intrusion = []
        self._alert_ids = set()
        self.update()

    def _on_blink(self) -> None:
        if not self._alerting:
            self._region_on = True
            self._blink.stop()
            self.update()
            return
        self._region_on = not self._region_on
        self.update()

    def _map_box(self, xyxy: list[float]) -> QRect:
        iw, ih = self._image_size
        sx = self.width() / iw
        sy = self.height() / ih
        x1, y1, x2, y2 = xyxy
        x = int(round(x1 * sx))
        y = int(round(y1 * sy))
        w = max(1, int(round((x2 - x1) * sx)))
        h = max(1, int(round((y2 - y1) * sy)))
        return QRect(x, y, w, h)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for item in self._parking:
            self._paint_item(p, item, self._settings.parking_conf)
        for item in self._intrusion:
            self._paint_item(p, item, self._settings.intrusion_conf)
        self._paint_region(p)

    def _paint_region(self, p: QPainter) -> None:
        if self._alerting and not self._region_on:
            return
        color = T.REGION_ALERT if self._alerting else T.REGION_RUN
        width = T.REGION_PEN
        inset = max(1, width // 2)
        box = self.rect().adjusted(inset, inset, -inset - 1, -inset - 1)
        p.setBrush(Qt.BrushStyle.NoBrush)

        pen = QPen(color, width)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([8, 6])
        p.setPen(pen)
        p.drawRect(box)
        # Draw L-corners last so they sit on top of the dashed stroke
        # and hide dash gaps at the four corners.
        self._paint_corners(p, self.rect(), color)

    def _paint_corners(self, p: QPainter, outer: QRect, color) -> None:
        length = min(T.REGION_CORNER_LEN, outer.width() // 3, outer.height() // 3)
        thick = T.REGION_CORNER_PEN
        if length < thick + 4:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        x1, y1 = outer.left(), outer.top()
        right = outer.right() - length + 1
        bottom = outer.bottom() - length + 1
        x2 = outer.right() - thick + 1
        y2 = outer.bottom() - thick + 1
        for rect in (
            QRect(x1, y1, length, thick),
            QRect(x1, y1, thick, length),
            QRect(right, y1, length, thick),
            QRect(x2, y1, thick, length),
            QRect(x1, y2, length, thick),
            QRect(x1, bottom, thick, length),
            QRect(right, y2, length, thick),
            QRect(x2, bottom, thick, length),
        ):
            p.drawRect(rect)

    def _paint_item(self, p: QPainter, item: dict, threshold: float) -> None:
        box = self._map_box(item.get("xyxy") or [0, 0, 0, 0])
        if box.width() < 1 or box.height() < 1:
            return
        conf = float(item.get("conf") or 0.0)
        high = conf >= threshold
        if not high and self._settings.hide_low_conf and id(item) not in self._alert_ids:
            return
        if id(item) in self._alert_ids:
            color = T.BOX_ALERT
        else:
            color = T.BOX_HIGH if high else T.BOX_LOW
        pen = QPen(color, T.BOX_PEN)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawRect(box)

        if not self._settings.show_labels:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(self.font())
        if not self._settings.demo_record:
            name = LABELS_ZH.get(str(item.get("name") or ""), str(item.get("name") or ""))
            self._paint_tag(p, box, f"{name} {conf:.2f}", above=True)
        still = int(item.get("still") or 0)
        if still > 0:
            self._paint_tag(p, box, str(still), above=False)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _paint_tag(self, p: QPainter, box: QRect, text: str, above: bool) -> None:
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 4
        if above:
            label = QRectF(box.x(), box.y() - th - 2, tw, th)
            if label.y() < 0:
                label.moveTop(box.y() + 2)
        else:
            label = QRectF(box.x(), box.bottom() + 2, tw, th)
            if label.bottom() > self.height():
                label.moveBottom(float(box.bottom() - 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.BOX_LABEL_BG)
        p.drawRect(label)
        p.setPen(T.BOX_LABEL)
        p.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
