"""Paginated metallic alert list."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
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
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from app import theme as T
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
        if self._view_rect().contains(pos):
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
            if self._view_rect().contains(pos):
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


class ImagePeek(QWidget):
    """Owned always-on-top preview so the photo stays above the list."""

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
        self._pixmap = QPixmap()
        self._hover = ""

    def show_image(self, path: Path, anchor: QRect) -> None:
        image = QImage(str(path))
        if image.isNull():
            self.hide()
            return
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        max_w = max(160, int(geo.width() * 0.86) - 32)
        max_h = max(120, int(geo.height() * 0.86) - 48)
        pix = QPixmap.fromImage(image)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(
                max_w,
                max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._pixmap = pix
        width = pix.width() + 32
        height = pix.height() + 48
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y() + (geo.height() - height) // 2
        self.setGeometry(x, y, width, height)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def _btn_close(self) -> QRect:
        size = 28
        return QRect(self.width() - 14 - size, 10, size, size)

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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hover = "close" if self._btn_close().contains(event.position().toPoint()) else ""
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
            if self._btn_close().contains(event.position().toPoint()):
                self.hide()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 16.0)
        if not self._pixmap.isNull():
            x = (self.width() - self._pixmap.width()) // 2
            y = 36 + (self.height() - 48 - self._pixmap.height()) // 2
            p.drawPixmap(x, y, self._pixmap)
        self._paint_close_x(p, self._btn_close(), self._hover == "close")


class AlertListWindow(QWidget):
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
        self.setWindowTitle("CarFind Alerts")
        self.setMouseTracking(True)
        self.setFont(_ui_font(13))
        self.setMinimumSize(T.LIST_MIN_W, T.LIST_MIN_H)
        self._chrome_ready = False
        self._hover = ""
        self.resume_after_close = True
        self._records: list[AlertRecord] = []
        self._rows: list[AlertRow] = []
        self._page = 0
        self._shown_keys: list[str] = []
        self._placed = False
        self._peek = ImagePeek(self)

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
        self._peek.show_image(record.path, self.frameGeometry())

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

    def _close_list(self) -> None:
        resume = bool(self.resume_after_close)
        self._peek.hide()
        self.hide()
        self.closed.emit(resume)

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

    def _check_box(self) -> QRect:
        close = self._btn_close()
        return QRect(close.x() - 12 - 132 - 8 - 18, (T.LIST_HEADER_H - 18) // 2, 18, 18)

    def _check_hit(self) -> QRect:
        box = self._check_box()
        close = self._btn_close()
        return QRect(box.x() - 4, 8, close.x() - box.x() - 8, T.LIST_HEADER_H - 16)

    def _btn_folder(self) -> QRect:
        return QRect(28, self.height() - 54, 132, 34)

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
        if self._btn_close().contains(pos) or self._check_hit().contains(pos):
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
            elif self._check_hit().contains(pos):
                hover = "resume"
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
            if self._check_hit().contains(pos):
                self.resume_after_close = not self.resume_after_close
                self.update()
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

        box = QRectF(self._check_box())
        p.setPen(QPen(T.WINDOW_RIM, 1.1))
        p.setBrush(QColor(255, 255, 255, 22 if self._hover == "resume" else 12))
        p.drawRoundedRect(box, 4.0, 4.0)
        if self.resume_after_close:
            p.setPen(QPen(T.ICON_GREEN, 1.8))
            p.drawLine(int(box.x() + 4), int(box.center().y()), int(box.x() + 7), int(box.bottom() - 4))
            p.drawLine(int(box.x() + 7), int(box.bottom() - 4), int(box.right() - 4), int(box.y() + 4))
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(13))
        p.drawText(
            QRect(self._check_box().right() + 8, 12, 132, 28),
            Qt.AlignmentFlag.AlignVCenter,
            "关闭后继续监测",
        )
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
