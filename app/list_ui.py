"""Paginated metallic alert list."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from app import theme as T
from app.config import load_settings
from app.hud import _paint_metal_panel, _ui_font
from app.paths import ensure_false_positive_dir, ensure_pic_dir
from app.win32util import apply_capture_affinity, disable_system_rounding

_NAME_RE = re.compile(
    r"^(P|V|PV)(\d{8})-(\d{6})(?:_(\d+))?\.png$",
    re.IGNORECASE,
)
_KIND_LABEL = {
    "P": "闯入",
    "V": "违停",
    "PV": "违停+闯入",
}


@dataclass
class AlertRecord:
    path: Path
    when: datetime
    kind: str
    suffix: int

    @property
    def kind_text(self) -> str:
        return _KIND_LABEL.get(self.kind, self.kind)

    @property
    def time_text(self) -> str:
        return self.when.strftime("%Y-%m-%d  %H:%M:%S")


def load_records() -> list[AlertRecord]:
    folder = ensure_pic_dir()
    out: list[AlertRecord] = []
    try:
        names = list(folder.iterdir())
    except OSError:
        return out
    for path in names:
        if not path.is_file():
            continue
        matched = _NAME_RE.match(path.name)
        if matched is None:
            continue
        kind = matched.group(1).upper()
        try:
            when = datetime.strptime(
                f"{matched.group(2)}-{matched.group(3)}",
                "%Y%m%d-%H%M%S",
            )
        except ValueError:
            continue
        suffix = int(matched.group(4) or 0)
        out.append(AlertRecord(path, when, kind, suffix))
    out.sort(key=lambda item: (item.when, item.suffix), reverse=True)
    return out


def _paint_metal_button(p: QPainter, rect: QRect, title: str, hover: bool, enabled: bool = True) -> None:
    body = QRectF(rect)
    p.setPen(QPen(T.WINDOW_RIM, 1.0))
    fill = QLinearGradient(body.topLeft(), body.bottomLeft())
    if not enabled:
        fill.setColorAt(0.0, QColor(48, 50, 54))
        fill.setColorAt(1.0, QColor(22, 24, 26))
    elif hover:
        fill.setColorAt(0.0, QColor(92, 98, 108))
        fill.setColorAt(1.0, QColor(38, 41, 46))
    else:
        fill.setColorAt(0.0, QColor(72, 76, 84))
        fill.setColorAt(1.0, QColor(28, 30, 34))
    p.setBrush(fill)
    p.drawRoundedRect(body, 8.0, 8.0)
    p.setPen(T.SETTINGS_MUTED if not enabled else T.SETTINGS_TEXT)
    p.setFont(_ui_font(13))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)


class AlertRow(QWidget):
    view_clicked = Signal(object)
    false_clicked = Signal(object)

    def __init__(self, record: AlertRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._record = record
        self._hover = ""
        self._thumb: QPixmap | None = None
        self._thumb_tried = False
        self._reported = (ensure_false_positive_dir() / record.path.name).is_file()
        self.setFixedHeight(T.LIST_ROW_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFont(_ui_font(14))

    def _thumb_rect(self) -> QRect:
        return QRect(18, 12, T.LIST_THUMB_W, T.LIST_THUMB_H)

    def _false_rect(self) -> QRect:
        return QRect(self.width() - 18 - 80, (self.height() - 36) // 2, 80, 36)

    def _view_rect(self) -> QRect:
        false = self._false_rect()
        return QRect(false.x() - 10 - 80, false.y(), 80, 36)

    def _hint_rect(self) -> QRect:
        left = self._view_rect().x()
        return QRect(left, self.height() - 34, self.width() - 18 - left, 18)

    def set_reported(self, reported: bool = True) -> None:
        flag = bool(reported)
        if flag == self._reported:
            return
        self._reported = flag
        self.update()

    def _ensure_thumb(self) -> QPixmap | None:
        if self._thumb_tried:
            return self._thumb
        self._thumb_tried = True
        image = QImage(str(self._record.path))
        if image.isNull():
            return None
        self._thumb = QPixmap.fromImage(
            image.scaled(
                T.LIST_THUMB_W,
                T.LIST_THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return self._thumb

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._view_rect().contains(pos) or self._thumb_rect().contains(pos):
            hover = "view"
        elif self._false_rect().contains(pos):
            hover = "false"
        else:
            hover = ""
        if hover != self._hover:
            self._hover = hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = ""
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._view_rect().contains(pos) or self._thumb_rect().contains(pos):
                self.view_clicked.emit(self._record)
                event.accept()
                return
            if self._false_rect().contains(pos):
                self.false_clicked.emit(self._record)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(8, 6, self.width() - 16, self.height() - 12)
        _paint_metal_panel(p, body, 14.0)

        frame = QRectF(self._thumb_rect())
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(QColor(8, 9, 11, 200))
        p.drawRoundedRect(frame, 8.0, 8.0)
        thumb = self._ensure_thumb()
        if thumb is not None and not thumb.isNull():
            tx = int(frame.x() + (frame.width() - thumb.width()) / 2)
            ty = int(frame.y() + (frame.height() - thumb.height()) / 2)
            p.drawPixmap(tx, ty, thumb)
        else:
            p.setPen(T.SETTINGS_MUTED)
            p.setFont(_ui_font(12))
            p.drawText(frame.toRect(), Qt.AlignmentFlag.AlignCenter, "无法预览")

        text_left = self._thumb_rect().right() + 24
        text_w = max(80, self._view_rect().x() - text_left - 16)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(16))
        p.drawText(
            QRect(text_left, 28, text_w, 28),
            Qt.AlignmentFlag.AlignVCenter,
            self._record.time_text,
        )
        p.setFont(_ui_font(18))
        if self._record.kind == "PV":
            p.setPen(T.BOX_ALERT)
        elif self._record.kind == "V":
            p.setPen(T.ICON_YELLOW)
        else:
            p.setPen(T.BOX_HIGH)
        p.drawText(
            QRect(text_left, 58, text_w, 32),
            Qt.AlignmentFlag.AlignVCenter,
            self._record.kind_text,
        )
        p.setPen(T.SETTINGS_MUTED)
        p.setFont(_ui_font(13))
        name = p.fontMetrics().elidedText(
            self._record.path.name,
            Qt.TextElideMode.ElideMiddle,
            text_w,
        )
        p.drawText(
            QRect(text_left, 94, text_w, 24),
            Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        _paint_metal_button(p, self._view_rect(), "查看", self._hover == "view")
        _paint_metal_button(p, self._false_rect(), "误报", self._hover == "false")
        if self._reported:
            p.setPen(T.SETTINGS_MUTED)
            p.setFont(_ui_font(11))
            p.drawText(
                self._hint_rect(),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "本条已上报错误",
            )


_ZOOM_MIN = 0.25
_ZOOM_MAX = 4.0
_ZOOM_STEP = 1.1
_CHROME_TOP = 52
_CHROME_SIDE = 16
_CHROME_BOTTOM = 16
_BTN_Y = 12
_BTN_SIZE = 28
_GUIDANCE_DELAY_MS = 1000
_GUIDANCE_ZOOM_SEC = 2.0
_GUIDANCE_FLASH_SEC = 5.0
_GUIDANCE_TICK_MS = 40


class ImagePeek(QWidget):
    """Owned always-on-top preview so the photo stays above the list."""

    closed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("CarFind Photo")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._chrome_ready = False
        self._records: list[AlertRecord] = []
        self._index = 0
        self._source = QPixmap()
        self._scaled = QPixmap()
        self._fit_w = 1
        self._fit_h = 1
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._auto_opened = False
        self._silent = False
        self._dragging = False
        self._drag_pos = QPoint()
        self._pan_origin = (0.0, 0.0)
        self._hover = ""
        self._alert_boxes: list[QRectF] = []
        self._guidance_mode = ""
        self._guidance_epoch = 0.0
        self._guidance_start_pan = (0.0, 0.0)
        self._guidance_final_pan = (0.0, 0.0)
        self._guidance_delay = QTimer(self)
        self._guidance_delay.setSingleShot(True)
        self._guidance_delay.setInterval(_GUIDANCE_DELAY_MS)
        self._guidance_delay.timeout.connect(self._begin_guidance)
        self._guidance_tick = QTimer(self)
        self._guidance_tick.setInterval(_GUIDANCE_TICK_MS)
        self._guidance_tick.timeout.connect(self._on_guidance_tick)

    def show_records(
        self,
        records: list[AlertRecord],
        index: int,
        anchor: QRect,
        auto_opened: bool = False,
    ) -> None:
        self._records = list(records)
        if not self._records:
            self.hide()
            return
        self._index = max(0, min(int(index), len(self._records) - 1))
        self._auto_opened = bool(auto_opened)
        self._load_current(anchor)

    def dismiss(self) -> None:
        self._auto_opened = False
        self._silent = True
        self.hide()
        self._silent = False

    def hideEvent(self, event) -> None:
        self._cancel_guidance()
        self._dragging = False
        auto = bool(self._auto_opened)
        self._auto_opened = False
        if not self._silent:
            self.closed.emit(auto)
        super().hideEvent(event)

    def _load_current(self, anchor: QRect) -> None:
        self._cancel_guidance()
        record = self._records[self._index]
        image = QImage(str(record.path))
        if image.isNull():
            self.hide()
            return
        self._alert_boxes = self._read_alert_boxes(image)
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        max_w = max(160, int(geo.width() * 0.86) - _CHROME_SIDE * 2)
        max_h = max(120, int(geo.height() * 0.86) - _CHROME_TOP - _CHROME_BOTTOM)
        source = QPixmap.fromImage(image)
        self._source = source
        if source.width() > max_w or source.height() > max_h:
            fit = source.scaled(
                max_w,
                max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            fit = source
        self._fit_w = max(1, fit.width())
        self._fit_h = max(1, fit.height())
        self._zoom = 1.0
        self._scaled = QPixmap()
        width = max(300, self._fit_w + _CHROME_SIDE * 2)
        width = min(width, geo.width())
        height = self._fit_h + _CHROME_TOP + _CHROME_BOTTOM
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y() + (geo.height() - height) // 2
        self.setGeometry(x, y, width, height)
        self._rebuild_scaled()
        self._clamp_pan()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.update()
        if load_settings().gaze_guidance and self._alert_boxes:
            self._guidance_delay.start()

    def _read_alert_boxes(self, image: QImage) -> list[QRectF]:
        raw = image.text(T.ALERT_BOX_METADATA_KEY)
        if not raw:
            return []
        try:
            values = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        boxes: list[QRectF] = []
        if not isinstance(values, list):
            return boxes
        for value in values:
            if not isinstance(value, list) or len(value) != 4:
                continue
            try:
                x, y, w, h = (float(part) for part in value)
            except (TypeError, ValueError):
                continue
            if w > 0.0 and h > 0.0:
                boxes.append(QRectF(x, y, w, h))
        return boxes

    def _cancel_guidance(self) -> None:
        self._guidance_delay.stop()
        self._guidance_tick.stop()
        if self._guidance_mode:
            self._guidance_mode = ""
            self.update()

    def _begin_guidance(self) -> None:
        if not self.isVisible() or not self._alert_boxes:
            return
        self._guidance_epoch = time.monotonic()
        if len(self._alert_boxes) == 1:
            box = self._alert_boxes[0]
            content = self._content_rect()
            sx = self._fit_w / max(1, self._source.width())
            sy = self._fit_h / max(1, self._source.height())
            target_zoom = 2.0
            desired_x = content.width() / 2.0 - box.center().x() * sx * target_zoom
            desired_y = content.height() / 2.0 - box.center().y() * sy * target_zoom
            self._guidance_start_pan = (self._pan_x, self._pan_y)
            self._guidance_final_pan = self._clamped_pan(
                target_zoom, desired_x, desired_y
            )
            self._guidance_mode = "zoom"
        else:
            self._guidance_mode = "circles"
        self._guidance_tick.start()
        self.update()

    def _on_guidance_tick(self) -> None:
        elapsed = max(0.0, time.monotonic() - self._guidance_epoch)
        if self._guidance_mode == "zoom":
            t = min(1.0, elapsed / _GUIDANCE_ZOOM_SEC)
            eased = t * t * (3.0 - 2.0 * t)
            self._zoom = 1.0 + eased
            self._pan_x = self._guidance_start_pan[0] + (
                self._guidance_final_pan[0] - self._guidance_start_pan[0]
            ) * eased
            self._pan_y = self._guidance_start_pan[1] + (
                self._guidance_final_pan[1] - self._guidance_start_pan[1]
            ) * eased
            self._rebuild_scaled()
            self._clamp_pan()
            if t >= 1.0:
                self._zoom = 2.0
                self._pan_x, self._pan_y = self._guidance_final_pan
                self._rebuild_scaled()
                self._clamp_pan()
                self._guidance_mode = ""
                self._guidance_tick.stop()
        elif self._guidance_mode == "circles":
            if elapsed >= _GUIDANCE_FLASH_SEC:
                self._guidance_mode = ""
                self._guidance_tick.stop()
        else:
            self._guidance_tick.stop()
        self.update()

    def _step(self, delta: int) -> None:
        nxt = self._index + delta
        if nxt < 0 or nxt >= len(self._records):
            return
        self._index = nxt
        self._load_current(self.frameGeometry())

    def _content_rect(self) -> QRect:
        return QRect(
            _CHROME_SIDE,
            _CHROME_TOP,
            max(1, self.width() - _CHROME_SIDE * 2),
            max(1, self.height() - _CHROME_TOP - _CHROME_BOTTOM),
        )

    def _rebuild_scaled(self) -> None:
        if self._source.isNull():
            self._scaled = QPixmap()
            return
        tw = max(1, int(round(self._fit_w * self._zoom)))
        th = max(1, int(round(self._fit_h * self._zoom)))
        if self._scaled.width() == tw and self._scaled.height() == th:
            return
        self._scaled = self._source.scaled(
            tw,
            th,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _can_pan(self) -> bool:
        if self._zoom <= 1.0 + 1e-6:
            return False
        content = self._content_rect()
        return self._scaled.width() > content.width() or self._scaled.height() > content.height()

    def _clamp_pan(self) -> None:
        self._pan_x, self._pan_y = self._clamped_pan(
            self._zoom, self._pan_x, self._pan_y
        )

    def _clamped_pan(self, zoom: float, pan_x: float, pan_y: float) -> tuple[float, float]:
        content = self._content_rect()
        sw = max(1, int(round(self._fit_w * zoom)))
        sh = max(1, int(round(self._fit_h * zoom)))
        cw, ch = content.width(), content.height()
        if sw <= cw:
            pan_x = (cw - sw) / 2.0
        else:
            pan_x = min(0.0, max(float(cw - sw), pan_x))
        if sh <= ch:
            pan_y = (ch - sh) / 2.0
        else:
            pan_y = min(0.0, max(float(ch - sh), pan_y))
        return pan_x, pan_y

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def _btn_close(self) -> QRect:
        return QRect(self.width() - 14 - _BTN_SIZE, _BTN_Y, _BTN_SIZE, _BTN_SIZE)

    def _btn_down(self) -> QRect:
        close = self._btn_close()
        return QRect(close.x() - 8 - _BTN_SIZE, close.y(), _BTN_SIZE, _BTN_SIZE)

    def _btn_up(self) -> QRect:
        down = self._btn_down()
        return QRect(down.x() - 8 - _BTN_SIZE, down.y(), _BTN_SIZE, _BTN_SIZE)

    def _btn_reset(self) -> QRect:
        return QRect(_CHROME_SIDE + 72, _BTN_Y, 82, _BTN_SIZE)

    def _reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._rebuild_scaled()
        self._clamp_pan()
        self.update()

    def _has_prev(self) -> bool:
        return self._index > 0

    def _has_next(self) -> bool:
        return self._index + 1 < len(self._records)

    def _paint_circle_btn(self, p: QPainter, rect: QRect, hover: bool, enabled: bool) -> QRectF:
        body = QRectF(rect)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if not enabled:
            fill.setColorAt(0.0, QColor(48, 50, 54))
            fill.setColorAt(1.0, QColor(22, 24, 26))
        elif hover:
            fill.setColorAt(0.0, QColor(92, 98, 108))
            fill.setColorAt(1.0, QColor(38, 41, 46))
        else:
            fill.setColorAt(0.0, QColor(72, 76, 84))
            fill.setColorAt(1.0, QColor(28, 30, 34))
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(fill)
        p.drawEllipse(body)
        return body

    def _paint_triangle(self, p: QPainter, rect: QRect, up: bool, hover: bool, enabled: bool) -> None:
        body = self._paint_circle_btn(p, rect, hover, enabled)
        inset = 8.0
        cx = body.center().x()
        if up:
            pts = [
                QPointF(cx, body.top() + inset),
                QPointF(body.left() + inset, body.bottom() - inset),
                QPointF(body.right() - inset, body.bottom() - inset),
            ]
        else:
            pts = [
                QPointF(cx, body.bottom() - inset),
                QPointF(body.left() + inset, body.top() + inset),
                QPointF(body.right() - inset, body.top() + inset),
            ]
        if not enabled:
            color = T.SETTINGS_MUTED
        elif hover:
            color = T.SETTINGS_TEXT
        else:
            color = T.ICON_SILVER
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF(pts))

    def _paint_close_x(self, p: QPainter, rect: QRect, hover: bool) -> None:
        body = QRectF(rect)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if hover:
            fill.setColorAt(0.0, QColor(108, 72, 72))
            fill.setColorAt(1.0, QColor(48, 22, 22))
        else:
            fill.setColorAt(0.0, QColor(72, 76, 84))
            fill.setColorAt(1.0, QColor(28, 30, 34))
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(fill)
        p.drawEllipse(body)
        inset = 8.0
        cross = QPen(T.ICON_SILVER if not hover else T.ICON_RED, 2.1)
        cross.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(cross)
        p.drawLine(
            int(body.left() + inset),
            int(body.top() + inset),
            int(body.right() - inset),
            int(body.bottom() - inset),
        )
        p.drawLine(
            int(body.right() - inset),
            int(body.top() + inset),
            int(body.left() + inset),
            int(body.bottom() - inset),
        )

    def _cursor_for(self, pos: QPoint):
        if self._btn_close().contains(pos):
            return Qt.CursorShape.PointingHandCursor
        if self._btn_up().contains(pos) and self._has_prev():
            return Qt.CursorShape.PointingHandCursor
        if self._btn_down().contains(pos) and self._has_next():
            return Qt.CursorShape.PointingHandCursor
        if self._btn_reset().contains(pos):
            return Qt.CursorShape.PointingHandCursor
        if self._can_pan() and self._content_rect().contains(pos):
            return Qt.CursorShape.OpenHandCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._cancel_guidance()
            pos = event.position().toPoint()
            if (
                self._btn_close().contains(pos)
                or self._btn_up().contains(pos)
                or self._btn_down().contains(pos)
                or self._btn_reset().contains(pos)
            ):
                event.accept()
                return
            if self._can_pan() and self._content_rect().contains(pos):
                self._dragging = True
                self._drag_pos = pos
                self._pan_origin = (self._pan_x, self._pan_y)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            delta = pos - self._drag_pos
            self._pan_x = self._pan_origin[0] + delta.x()
            self._pan_y = self._pan_origin[1] + delta.y()
            self._clamp_pan()
            self.update()
            event.accept()
            return
        hover = ""
        if self._btn_close().contains(pos):
            hover = "close"
        elif self._btn_up().contains(pos) and self._has_prev():
            hover = "up"
        elif self._btn_down().contains(pos) and self._has_next():
            hover = "down"
        elif self._btn_reset().contains(pos):
            hover = "reset"
        self.setCursor(self._cursor_for(pos))
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = ""
            if not self._dragging:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._dragging:
                self._dragging = False
                self.setCursor(self._cursor_for(pos))
                event.accept()
                return
            if self._btn_close().contains(pos):
                self.hide()
                event.accept()
                return
            if self._btn_up().contains(pos):
                self._step(-1)
                event.accept()
                return
            if self._btn_down().contains(pos):
                self._step(1)
                event.accept()
                return
            if self._btn_reset().contains(pos):
                self._reset_zoom()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._source.isNull():
            return
        self._cancel_guidance()
        dy = event.angleDelta().y()
        if dy == 0:
            event.accept()
            return
        steps = dy / 120.0
        old = self._zoom
        new = max(_ZOOM_MIN, min(_ZOOM_MAX, old * (_ZOOM_STEP ** steps)))
        if abs(new - 1.0) < 0.03:
            new = 1.0
        if abs(new - old) < 1e-6:
            event.accept()
            return
        content = self._content_rect()
        pos = event.position()
        cx = pos.x() - content.x()
        cy = pos.y() - content.y()
        fit_x = (cx - self._pan_x) / old if old else 0.0
        fit_y = (cy - self._pan_y) / old if old else 0.0
        self._zoom = new
        self._pan_x = cx - fit_x * new
        self._pan_y = cy - fit_y * new
        self._rebuild_scaled()
        self._clamp_pan()
        self.setCursor(self._cursor_for(event.position().toPoint()))
        self.update()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self._cancel_guidance()
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        if event.key() == Qt.Key.Key_PageUp:
            self._step(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_PageDown:
            self._step(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _paint_guidance_circles(self, p: QPainter, content: QRect) -> None:
        if self._guidance_mode != "circles" or self._source.isNull():
            return
        elapsed = max(0.0, time.monotonic() - self._guidance_epoch)
        if int(elapsed / 0.5) % 2 != 0:
            return
        sx = self._fit_w / max(1, self._source.width()) * self._zoom
        sy = self._fit_h / max(1, self._source.height()) * self._zoom
        pen = QPen(T.BOX_ALERT, 3.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for box in self._alert_boxes:
            cx = content.x() + self._pan_x + box.center().x() * sx
            cy = content.y() + self._pan_y + box.center().y() * sy
            bw = box.width() * sx
            bh = box.height() * sy
            diameter = max(18.0, (bw * bw + bh * bh) ** 0.5 * 1.12)
            p.drawEllipse(
                QRectF(
                    cx - diameter / 2.0,
                    cy - diameter / 2.0,
                    diameter,
                    diameter,
                )
            )

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 16.0)
        content = self._content_rect()
        p.save()
        p.setClipRect(content)
        if not self._scaled.isNull():
            p.drawPixmap(int(content.x() + self._pan_x), int(content.y() + self._pan_y), self._scaled)
        self._paint_guidance_circles(p, content)
        p.restore()
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(12))
        p.drawText(
            QRect(_CHROME_SIDE, _BTN_Y, 72, _BTN_SIZE),
            Qt.AlignmentFlag.AlignVCenter,
            f"{int(round(self._zoom * 100))}%",
        )
        _paint_metal_button(
            p,
            self._btn_reset(),
            "复原缩放",
            self._hover == "reset",
            abs(self._zoom - 1.0) > 1e-6,
        )
        self._paint_triangle(p, self._btn_up(), True, self._hover == "up", self._has_prev())
        self._paint_triangle(p, self._btn_down(), False, self._hover == "down", self._has_next())
        self._paint_close_x(p, self._btn_close(), self._hover == "close")


class AlertListWindow(QWidget):
    closed = Signal()
    stats_requested = Signal()
    peek_closed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("CarFind Alerts")
        self.setMouseTracking(True)
        self.setFont(_ui_font(13))
        self.setMinimumSize(T.LIST_MIN_W, T.LIST_MIN_H)
        self._chrome_ready = False
        self._hover = ""
        self._records: list[AlertRecord] = []
        self._rows: list[AlertRow] = []
        self._page = 0
        self._shown_keys: list[str] = []
        self._placed = False
        self._peek = ImagePeek(parent)
        self._peek.closed.connect(self.peek_closed.emit)

    def show_at(self, anchor: QRect) -> None:
        if not self.isVisible():
            self._place_default(anchor)
        self._page = 0
        self._reload()
        self.show()
        self.raise_()
        self.activateWindow()
        self._apply_page(force=True)
        self.update()

    def _place_default(self, anchor: QRect) -> None:
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        width = max(T.LIST_MIN_W, int(geo.width() * 0.8))
        height = max(T.LIST_MIN_H, int(geo.height() * 0.8))
        width = min(width, geo.width())
        height = min(height, geo.height())
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y() + (geo.height() - height) // 2
        self.setGeometry(x, y, width, height)
        self._placed = True

    def _reload(self) -> None:
        self._records = load_records()
        self._apply_page(force=True)
        self.update()

    def _page_size(self) -> int:
        body = self.height() - T.LIST_HEADER_H - T.LIST_FOOTER_H
        fit = max(1, body // T.LIST_ROW_H)
        return min(T.LIST_PAGE_MAX, fit)

    def _page_count(self) -> int:
        size = max(1, self._page_size())
        if not self._records:
            return 1
        return max(1, int(ceil(len(self._records) / size)))

    def _apply_page(self, force: bool = False) -> None:
        pages = self._page_count()
        self._page = max(0, min(self._page, pages - 1))
        size = self._page_size()
        start = self._page * size
        chunk = self._records[start : start + size]
        keys = [str(item.path) for item in chunk]
        if not force and keys == self._shown_keys:
            self._layout_rows()
            return
        self._shown_keys = keys
        for old in self._rows:
            old.setParent(None)
            old.deleteLater()
        self._rows = []
        for record in chunk:
            row = AlertRow(record, self)
            row.view_clicked.connect(self._open_image)
            row.false_clicked.connect(self._mark_false_positive)
            row.show()
            self._rows.append(row)
        self._layout_rows()
        self.update()

    def _layout_rows(self) -> None:
        y = T.LIST_HEADER_H
        width = max(1, self.width() - 16)
        for row in self._rows:
            row.setGeometry(8, y, width, T.LIST_ROW_H)
            y += T.LIST_ROW_H

    def _open_image(self, record: AlertRecord) -> None:
        self._peek.show_records(
            self._records,
            self._index_of(record),
            self.frameGeometry(),
            auto_opened=False,
        )

    def _index_of(self, record: AlertRecord) -> int:
        for i, item in enumerate(self._records):
            if item.path == record.path:
                return i
        return 0

    def open_saved_image(self, path: Path, anchor: QRect) -> None:
        self._records = load_records()
        index = 0
        target = path
        try:
            target = path.resolve()
        except OSError:
            pass
        for i, rec in enumerate(self._records):
            same = rec.path == path or rec.path.name == path.name
            if not same:
                try:
                    same = rec.path.resolve() == target
                except OSError:
                    same = False
            if same:
                index = i
                break
        self._peek.show_records(self._records, index, anchor, auto_opened=True)

    def dismiss_peek(self) -> None:
        self._peek.dismiss()

    def close_peek(self) -> None:
        """Hide the viewer the same way as clicking X (emits closed)."""
        if self._peek.isVisible():
            self._peek.hide()

    def _mark_false_positive(self, record: AlertRecord) -> None:
        src = record.path
        if not src.is_file():
            return
        dest = ensure_false_positive_dir() / src.name
        if not dest.exists():
            try:
                shutil.copy2(src, dest)
            except OSError:
                return
        if not dest.exists():
            return
        for row in self._rows:
            if row._record.path == src:
                row.set_reported(True)
                break

    def _open_folder(self) -> None:
        try:
            os.startfile(str(ensure_pic_dir()))
        except OSError:
            pass

    def _open_stats(self) -> None:
        self.dismiss_peek()
        self.hide()
        self.stats_requested.emit()

    def reveal(self) -> None:
        self._reload()
        self.show()
        self.raise_()
        self.activateWindow()

    def _close_list(self) -> None:
        self.dismiss_peek()
        self.hide()
        self.closed.emit()

    def _turn_page(self, delta: int) -> None:
        nxt = self._page + delta
        if nxt < 0 or nxt >= self._page_count():
            return
        self._page = nxt
        self._apply_page(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def resizeEvent(self, event) -> None:
        self._apply_page()
        super().resizeEvent(event)

    def _btn_close(self) -> QRect:
        size = 28
        return QRect(self.width() - 16 - size, (T.LIST_HEADER_H - size) // 2, size, size)

    def _btn_folder(self) -> QRect:
        return QRect(28, self.height() - 54, 132, 34)

    def _btn_stats(self) -> QRect:
        folder = self._btn_folder()
        return QRect(folder.right() + 12, folder.y(), 132, 34)

    def _btn_next(self) -> QRect:
        return QRect(self.width() - 28 - 72, self.height() - 54, 72, 34)

    def _page_label(self) -> QRect:
        nxt = self._btn_next()
        return QRect(nxt.x() - 58, self.height() - 54, 52, 34)

    def _btn_prev(self) -> QRect:
        label = self._page_label()
        return QRect(label.x() - 80, self.height() - 54, 72, 34)

    def _header_hit(self, pos: QPoint) -> bool:
        if pos.y() > T.LIST_HEADER_H:
            return False
        if self._btn_close().contains(pos):
            return False
        return True

    def _paint_close_x(self, p: QPainter, rect: QRect, hover: bool) -> None:
        body = QRectF(rect)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if hover:
            fill.setColorAt(0.0, QColor(108, 72, 72))
            fill.setColorAt(1.0, QColor(48, 22, 22))
        else:
            fill.setColorAt(0.0, QColor(72, 76, 84))
            fill.setColorAt(1.0, QColor(28, 30, 34))
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(fill)
        p.drawEllipse(body)
        inset = 8.0
        cross = QPen(T.ICON_SILVER if not hover else T.ICON_RED, 2.1)
        cross.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(cross)
        p.drawLine(
            int(body.left() + inset),
            int(body.top() + inset),
            int(body.right() - inset),
            int(body.bottom() - inset),
        )
        p.drawLine(
            int(body.right() - inset),
            int(body.top() + inset),
            int(body.left() + inset),
            int(body.bottom() - inset),
        )

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        m = T.LIST_EDGE
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges: Qt.Edge):
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            handle = self.windowHandle()
            edges = self._edges_at(pos)
            if edges and handle is not None:
                handle.startSystemResize(edges)
                event.accept()
                return
            if self._header_hit(pos) and handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        edges = self._edges_at(pos)
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            hover = ""
            if self._btn_close().contains(pos):
                hover = "close"
            elif self._btn_folder().contains(pos):
                hover = "folder"
            elif self._btn_stats().contains(pos):
                hover = "stats"
            elif self._btn_prev().contains(pos) and self._page > 0:
                hover = "prev"
            elif self._btn_next().contains(pos) and self._page + 1 < self._page_count():
                hover = "next"
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor
            )
            if hover != self._hover:
                self._hover = hover
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._btn_close().contains(pos):
                self._close_list()
                event.accept()
                return
            if self._btn_folder().contains(pos):
                self._open_folder()
                event.accept()
                return
            if self._btn_stats().contains(pos):
                self._open_stats()
                event.accept()
                return
            if self._btn_prev().contains(pos):
                self._turn_page(-1)
                event.accept()
                return
            if self._btn_next().contains(pos):
                self._turn_page(1)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        dy = event.angleDelta().y()
        if dy > 0:
            self._turn_page(-1)
        elif dy < 0:
            self._turn_page(1)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close_list()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left:
            self._turn_page(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self._turn_page(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "show_exit_popup"):
            parent.show_exit_popup(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 18.0)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(16))
        p.drawText(QRect(24, 14, 160, 28), Qt.AlignmentFlag.AlignVCenter, "预警列表")
        self._paint_close_x(p, self._btn_close(), self._hover == "close")

        pages = self._page_count()
        if not self._records:
            p.setPen(T.SETTINGS_MUTED)
            p.setFont(_ui_font(15))
            area = QRect(
                18,
                T.LIST_HEADER_H,
                self.width() - 36,
                self.height() - T.LIST_HEADER_H - T.LIST_FOOTER_H,
            )
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "暂无预警记录")

        _paint_metal_button(p, self._btn_folder(), "打开文件夹", self._hover == "folder")
        _paint_metal_button(p, self._btn_stats(), "统计与分析", self._hover == "stats")
        _paint_metal_button(p, self._btn_prev(), "上一页", self._hover == "prev", self._page > 0)
        p.setPen(T.SETTINGS_MUTED)
        p.setFont(_ui_font(12))
        p.drawText(
            self._page_label(),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._page + 1}/{pages}",
        )
        _paint_metal_button(
            p, self._btn_next(), "下一页", self._hover == "next", self._page + 1 < pages
        )
