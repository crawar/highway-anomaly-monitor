"""Metallic alert statistics window."""

from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from app import theme as T
from app.hud import _paint_metal_panel, _ui_font
from app.list_ui import _paint_metal_button, load_records
from app.win32util import apply_capture_affinity, disable_system_rounding

_WEEK = ("一", "二", "三", "四", "五", "六", "日")


def _tally(
    records,
    start: date,
    end: date,
    split_multi: bool,
) -> tuple[int, int, int, int]:
    parking = 0
    intrusion = 0
    congestion = 0
    both = 0
    lo, hi = (start, end) if start <= end else (end, start)
    for item in records:
        day = item.when.date()
        if day < lo or day > hi:
            continue
        if item.kind == "PV":
            if split_multi:
                parking += 1
                intrusion += 1
            else:
                both += 1
        elif item.kind == "V":
            parking += 1
        elif item.kind == "B":
            congestion += 1
        elif item.kind == "P":
            intrusion += 1
    return parking, intrusion, congestion, both


class MetalCalendar(QWidget):
    picked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(292, 286)
        self.setMouseTracking(True)
        self.setFont(_ui_font(13))
        self._chrome_ready = False
        self._shown = date.today().replace(day=1)
        self._chosen = date.today()
        self._hover = ""

    def popup(self, anchor: QRect, current: date) -> None:
        self._chosen = current
        self._shown = current.replace(day=1)
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        x = min(max(anchor.x(), geo.x() + 4), geo.right() - self.width() - 4)
        y = anchor.bottom() + 6
        if y + self.height() > geo.bottom() - 4:
            y = anchor.y() - self.height() - 6
        self.move(x, y)
        self.show()
        self.raise_()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def _shift_month(self, delta: int) -> None:
        month = self._shown.month + delta
        year = self._shown.year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        self._shown = date(year, month, 1)
        self.update()

    def _prev_rect(self) -> QRect:
        return QRect(12, 12, 28, 24)

    def _next_rect(self) -> QRect:
        return QRect(self.width() - 40, 12, 28, 24)

    def _grid_origin(self) -> QPoint:
        return QPoint(14, 72)

    def _cell_size(self) -> tuple[int, int]:
        return 38, 32

    def _days(self) -> list[date | None]:
        cal = calendar.Calendar(firstweekday=0)
        cells: list[date | None] = []
        for day in cal.itermonthdates(self._shown.year, self._shown.month):
            cells.append(day if day.month == self._shown.month else None)
        while len(cells) < 42:
            cells.append(None)
        return cells[:42]

    def _cell_rect(self, index: int) -> QRect:
        cw, ch = self._cell_size()
        origin = self._grid_origin()
        col = index % 7
        row = index // 7
        return QRect(origin.x() + col * cw, origin.y() + row * ch, cw - 2, ch - 2)

    def _hit_day(self, pos: QPoint) -> date | None:
        for i, day in enumerate(self._days()):
            if day is not None and self._cell_rect(i).contains(pos):
                return day
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        hover = ""
        if self._prev_rect().contains(pos):
            hover = "prev"
        elif self._next_rect().contains(pos):
            hover = "next"
        elif self._hit_day(pos) is not None:
            hover = "day"
        if hover != self._hover:
            self._hover = hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        pos = event.position().toPoint()
        if self._prev_rect().contains(pos):
            self._shift_month(-1)
            event.accept()
            return
        if self._next_rect().contains(pos):
            self._shift_month(1)
            event.accept()
            return
        day = self._hit_day(pos)
        if day is not None:
            self.picked.emit(day)
            self.hide()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 14.0)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(14))
        p.drawText(
            QRect(48, 10, self.width() - 96, 28),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._shown.year}年{self._shown.month}月",
        )
        p.setFont(_ui_font(16))
        p.drawText(self._prev_rect(), Qt.AlignmentFlag.AlignCenter, "‹")
        p.drawText(self._next_rect(), Qt.AlignmentFlag.AlignCenter, "›")
        p.setFont(_ui_font(12))
        p.setPen(T.SETTINGS_MUTED)
        origin = self._grid_origin()
        cw, ch = self._cell_size()
        for i, label in enumerate(_WEEK):
            p.drawText(
                QRect(origin.x() + i * cw, 46, cw - 2, 22),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        today = date.today()
        for i, day in enumerate(self._days()):
            cell = self._cell_rect(i)
            if day is None:
                continue
            if day == self._chosen:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(56, 168, 255, 70))
                p.drawRoundedRect(QRectF(cell), 6.0, 6.0)
            elif day == today:
                p.setPen(QPen(T.BOX_HIGH, 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(cell).adjusted(1, 1, -1, -1), 6.0, 6.0)
            p.setPen(T.SETTINGS_TEXT)
            p.setFont(_ui_font(13))
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(day.day))


class StatsWindow(QWidget):
    closed = Signal()
    back_to_list = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("CarFind Stats")
        self.setMouseTracking(True)
        self.setFont(_ui_font(13))
        self.setMinimumSize(T.LIST_MIN_W, 420)
        self._chrome_ready = False
        self._hover = ""
        self._split = True
        self._records = []
        self._start = date.today()
        self._end = date.today()
        self._picking = ""
        self._cal = MetalCalendar(self)
        self._cal.picked.connect(self._on_date_picked)

    def show_at(self, geo: QRect) -> None:
        self._records = load_records()
        self._split = True
        if self._records:
            days = [item.when.date() for item in self._records]
            self._start = min(days)
            self._end = max(days)
        else:
            today = date.today()
            self._start = today
            self._end = today
        if geo.width() >= self.minimumWidth() and geo.height() >= self.minimumHeight():
            self.setGeometry(geo)
        else:
            self._place_default(geo)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def _place_default(self, anchor: QRect) -> None:
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        width = max(self.minimumWidth(), int(area.width() * 0.8))
        height = max(self.minimumHeight(), int(area.height() * 0.8))
        width = min(width, area.width())
        height = min(height, area.height())
        x = area.x() + (area.width() - width) // 2
        y = area.y() + (area.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def _btn_close(self) -> QRect:
        size = 28
        return QRect(self.width() - 16 - size, (T.LIST_HEADER_H - size) // 2, size, size)

    def _chip_start(self) -> QRect:
        return QRect(78, 62, 128, 30)

    def _chip_end(self) -> QRect:
        return QRect(278, 62, 128, 30)

    def _check_box(self) -> QRect:
        return QRect(28, self.height() - 50, 18, 18)

    def _check_hit(self) -> QRect:
        box = self._check_box()
        return QRect(box.x() - 4, self.height() - 58, 196, 34)

    def _btn_back(self) -> QRect:
        return QRect(self.width() - 28 - 110, self.height() - 54, 110, 34)

    def _content(self) -> QRect:
        return QRect(
            18,
            104,
            self.width() - 36,
            self.height() - 104 - T.LIST_FOOTER_H,
        )

    def _pie_rect(self) -> QRectF:
        area = self._content()
        side = min(area.height() - 16, int(area.width() * 0.42), 280)
        side = max(140, side)
        y = area.y() + (area.height() - side) // 2
        return QRectF(area.x() + 20, y, side, side)

    def _text_rect(self) -> QRect:
        pie = self._pie_rect()
        area = self._content()
        left = int(pie.right()) + 36
        return QRect(left, area.y() + 12, max(80, area.right() - left), area.height() - 24)

    def _header_hit(self, pos: QPoint) -> bool:
        if pos.y() > T.LIST_HEADER_H:
            return False
        return not self._btn_close().contains(pos)

    def _on_date_picked(self, day: date) -> None:
        if self._picking == "start":
            self._start = day
            if self._start > self._end:
                self._end = self._start
        elif self._picking == "end":
            self._end = day
            if self._end < self._start:
                self._start = self._end
        self._picking = ""
        self.update()

    def _open_cal(self, which: str, chip: QRect) -> None:
        self._picking = which
        current = self._start if which == "start" else self._end
        self._cal.popup(QRect(self.mapToGlobal(chip.topLeft()), chip.size()), current)

    def _close_stats(self) -> None:
        self._cal.hide()
        self.hide()
        self.closed.emit()

    def _return_list(self) -> None:
        self._cal.hide()
        self.hide()
        self.back_to_list.emit()

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

    def _paint_chip(self, p: QPainter, rect: QRect, text: str, hover: bool) -> None:
        body = QRectF(rect)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if hover:
            fill.setColorAt(0.0, QColor(92, 98, 108))
            fill.setColorAt(1.0, QColor(38, 41, 46))
        else:
            fill.setColorAt(0.0, QColor(72, 76, 84))
            fill.setColorAt(1.0, QColor(28, 30, 34))
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(body, 8.0, 8.0)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(13))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_pie(self, p: QPainter, slices: list[tuple[int, QColor]]) -> None:
        box = self._pie_rect()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(T.WINDOW_RIM, 1.2))
        p.setBrush(QColor(18, 20, 24, 220))
        p.drawEllipse(box)
        total = sum(item[0] for item in slices)
        if total <= 0:
            p.setPen(T.SETTINGS_MUTED)
            p.setFont(_ui_font(14))
            p.drawText(box.toRect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return
        start = 90 * 16
        leftover = -360 * 16
        visible = [(count, color) for count, color in slices if count > 0]
        for i, (count, color) in enumerate(visible):
            if i == len(visible) - 1:
                span = leftover
            else:
                span = -int(round(360 * 16 * count / total))
                leftover -= span
            p.setPen(QPen(QColor(8, 9, 11, 160), 1.4))
            p.setBrush(color)
            p.drawPie(box.adjusted(6, 6, -6, -6), start, span)
            start += span

    def _paint_rows(self, p: QPainter, rows: list[tuple[str, QColor, int, str]]) -> None:
        area = self._text_rect()
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(16))
        p.drawText(
            QRect(area.x(), area.y(), area.width(), 28),
            Qt.AlignmentFlag.AlignVCenter,
            "分类统计",
        )
        y = area.y() + 44
        for name, color, count, pct in rows:
            swatch = QRect(area.x(), y + 8, 14, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(swatch), 3.0, 3.0)
            p.setPen(T.SETTINGS_TEXT)
            p.setFont(_ui_font(15))
            p.drawText(
                QRect(area.x() + 24, y, 120, 30),
                Qt.AlignmentFlag.AlignVCenter,
                name,
            )
            p.setFont(_ui_font(18))
            p.drawText(
                QRect(area.x() + 150, y, 80, 30),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                str(count),
            )
            p.setPen(T.SETTINGS_MUTED)
            p.setFont(_ui_font(15))
            p.drawText(
                QRect(area.x() + 244, y, 90, 30),
                Qt.AlignmentFlag.AlignVCenter,
                pct,
            )
            y += 42
        total = sum(item[2] for item in rows)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(15))
        p.drawText(
            QRect(area.x(), y + 8, area.width(), 28),
            Qt.AlignmentFlag.AlignVCenter,
            f"合计  {total}",
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
            elif self._chip_start().contains(pos):
                hover = "start"
            elif self._chip_end().contains(pos):
                hover = "end"
            elif self._check_hit().contains(pos):
                hover = "split"
            elif self._btn_back().contains(pos):
                hover = "back"
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
                self._close_stats()
                event.accept()
                return
            if self._chip_start().contains(pos):
                self._open_cal("start", self._chip_start())
                event.accept()
                return
            if self._chip_end().contains(pos):
                self._open_cal("end", self._chip_end())
                event.accept()
                return
            if self._check_hit().contains(pos):
                self._split = not self._split
                self.update()
                event.accept()
                return
            if self._btn_back().contains(pos):
                self._return_list()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close_stats()
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
        p.drawText(QRect(24, 14, 180, 28), Qt.AlignmentFlag.AlignVCenter, "统计与分析")
        self._paint_close_x(p, self._btn_close(), self._hover == "close")

        p.setPen(T.SETTINGS_MUTED)
        p.setFont(_ui_font(13))
        p.drawText(QRect(28, 62, 48, 30), Qt.AlignmentFlag.AlignVCenter, "起点")
        p.drawText(QRect(228, 62, 48, 30), Qt.AlignmentFlag.AlignVCenter, "终点")
        self._paint_chip(
            p,
            self._chip_start(),
            self._start.strftime("%Y-%m-%d"),
            self._hover == "start",
        )
        self._paint_chip(
            p,
            self._chip_end(),
            self._end.strftime("%Y-%m-%d"),
            self._hover == "end",
        )

        parking, intrusion, congestion, both = _tally(self._records, self._start, self._end, self._split)
        congestion_color = QColor(255, 148, 48)
        if self._split:
            slices = [
                (parking, T.ICON_YELLOW),
                (intrusion, T.BOX_HIGH),
                (congestion, congestion_color),
            ]
            total = parking + intrusion + congestion
            rows = [
                ("违停", T.ICON_YELLOW, parking, _pct(parking, total)),
                ("闯入", T.BOX_HIGH, intrusion, _pct(intrusion, total)),
                ("拥堵", congestion_color, congestion, _pct(congestion, total)),
            ]
        else:
            slices = [
                (parking, T.ICON_YELLOW),
                (intrusion, T.BOX_HIGH),
                (congestion, congestion_color),
                (both, T.BOX_ALERT),
            ]
            total = parking + intrusion + congestion + both
            rows = [
                ("违停", T.ICON_YELLOW, parking, _pct(parking, total)),
                ("闯入", T.BOX_HIGH, intrusion, _pct(intrusion, total)),
                ("拥堵", congestion_color, congestion, _pct(congestion, total)),
                ("违停+闯入", T.BOX_ALERT, both, _pct(both, total)),
            ]
        self._paint_pie(p, slices)
        self._paint_rows(p, rows)

        box = QRectF(self._check_box())
        p.setPen(QPen(T.WINDOW_RIM, 1.1))
        p.setBrush(QColor(255, 255, 255, 22 if self._hover == "split" else 12))
        p.drawRoundedRect(box, 4.0, 4.0)
        if self._split:
            p.setPen(QPen(T.ICON_GREEN, 1.8))
            p.drawLine(int(box.x() + 4), int(box.center().y()), int(box.x() + 7), int(box.bottom() - 4))
            p.drawLine(int(box.x() + 7), int(box.bottom() - 4), int(box.right() - 4), int(box.y() + 4))
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(13))
        p.drawText(
            QRect(self._check_box().right() + 8, self.height() - 54, 160, 28),
            Qt.AlignmentFlag.AlignVCenter,
            "多重预警单独显示",
        )
        _paint_metal_button(p, self._btn_back(), "返回列表", self._hover == "back")


def _pct(count: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{count * 100.0 / total:.1f}%"
