"""Vector icons drawn with QPainter."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from app import theme as T


def _icon_rect(btn: QRectF, scale: float = 0.58) -> QRectF:
    side = btn.width() * scale
    r = QRectF(0, 0, side, side)
    r.moveCenter(btn.center())
    return r


def draw_play_triangle(p: QPainter, btn: QRectF) -> None:
    r = _icon_rect(btn, 0.54)
    c = r.center()
    pts = QPolygonF(
        [
            QPointF(c.x() - r.width() * 0.22, c.y() - r.height() * 0.30),
            QPointF(c.x() - r.width() * 0.22, c.y() + r.height() * 0.30),
            QPointF(c.x() + r.width() * 0.36, c.y()),
        ]
    )
    g = QLinearGradient(pts[0], pts[2])
    g.setColorAt(0.0, T.ICON_GREEN)
    g.setColorAt(1.0, T.ICON_GREEN_DARK)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPolygon(pts)
    p.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(pts)


def draw_stop_square(p: QPainter, btn: QRectF, breath: float) -> None:
    scale = 0.34 + 0.05 * breath
    side = btn.width() * scale
    r = QRectF(0, 0, side, side)
    r.moveCenter(btn.center())
    alpha = int(140 + 115 * breath)
    glow = QColor(T.ICON_RED_GLOW)
    glow.setAlpha(int(40 + 70 * breath))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawRoundedRect(r.adjusted(-2.2, -2.2, 2.2, 2.2), 3.2, 3.2)
    fill = QColor(T.ICON_RED)
    fill.setAlpha(alpha)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0.0, QColor(255, 110, 100, alpha))
    g.setColorAt(1.0, fill)
    p.setBrush(g)
    p.drawRoundedRect(r, 2.4, 2.4)
    p.setPen(QPen(QColor(255, 255, 255, int(50 + 40 * breath)), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r.adjusted(0.4, 0.4, -0.4, -0.4), 2.0, 2.0)


def draw_dashed_square(p: QPainter, btn: QRectF, color: QColor, blink: float) -> None:
    r = _icon_rect(btn, 0.50)
    c = QColor(color)
    c.setAlpha(int(90 + 165 * blink))
    pen = QPen(c, 1.7)
    pen.setStyle(Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([2.4, 1.9])
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r, 2.5, 2.5)


def draw_folder(p: QPainter, btn: QRectF) -> None:
    r = _icon_rect(btn, 0.56)
    tab_h = r.height() * 0.22
    tab_w = r.width() * 0.42
    tab = QRectF(r.x() + r.width() * 0.06, r.y() + r.height() * 0.10, tab_w, tab_h + 2)
    body = QRectF(
        r.x() + r.width() * 0.06,
        r.y() + r.height() * 0.26,
        r.width() * 0.88,
        r.height() * 0.58,
    )
    tab_path = QPainterPath()
    tab_path.addRoundedRect(tab, 2.0, 2.0)
    body_path = QPainterPath()
    body_path.addRoundedRect(body, 2.4, 2.4)
    g = QLinearGradient(body.topLeft(), body.bottomLeft())
    g.setColorAt(0.0, QColor(245, 247, 250))
    g.setColorAt(1.0, T.FOLDER_BODY)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(T.FOLDER_TAB)
    p.drawPath(tab_path)
    p.setBrush(g)
    p.drawPath(body_path)
    p.setPen(QPen(T.FOLDER_LINE, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body_path)
    p.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
    p.drawLine(
        QPointF(body.left() + 3, body.top() + 1.2),
        QPointF(body.right() - 3, body.top() + 1.2),
    )


def make_gear_path(radius: float, teeth: int = 8) -> QPainterPath:
    r_out = radius
    r_root = radius * 0.68
    r_hole = radius * 0.28
    tooth_w = math.pi / teeth * 0.32
    path = QPainterPath()
    pts: list[QPointF] = []
    for i in range(teeth):
        a = i * (2 * math.pi / teeth) - math.pi / 2
        a0 = a - math.pi / teeth + tooth_w
        a1 = a - tooth_w
        a2 = a + tooth_w
        a3 = a + math.pi / teeth - tooth_w
        for ang, rad in (
            (a0, r_root),
            (a1, r_out),
            (a2, r_out),
            (a3, r_root),
        ):
            pts.append(QPointF(math.cos(ang) * rad, math.sin(ang) * rad))
    path.moveTo(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), r_hole, r_hole)
    return path.subtracted(hole)


def draw_gear(p: QPainter, btn: QRectF, rotation_deg: float) -> None:
    r = _icon_rect(btn, 0.56)
    path = make_gear_path(r.width() * 0.48)
    p.save()
    p.translate(r.center())
    p.rotate(rotation_deg)
    g = QLinearGradient(QPointF(-r.width() / 2, -r.height() / 2), QPointF(r.width() / 2, r.height() / 2))
    g.setColorAt(0.0, QColor(248, 250, 252))
    g.setColorAt(1.0, QColor(168, 176, 186))
    p.setBrush(g)
    p.setPen(QPen(QColor(30, 34, 38, 80), 0.8))
    p.drawPath(path)
    p.restore()


def draw_collapse_chevrons(p: QPainter, btn: QRectF, folded: float) -> None:
    r = _icon_rect(btn, 0.50)
    c = r.center()
    w = r.width() * 0.16
    h = r.height() * 0.22
    # 0 = expanded (chevrons point right, fold inward), 1 = collapsed (point left)
    direction = 1.0 - 2.0 * folded
    color = T.ICON_SILVER
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for offset in (-w * 0.85, w * 0.85):
        x = c.x() + offset
        p.drawPolyline(
            QPolygonF(
                [
                    QPointF(x - w * 0.7 * direction, c.y() - h),
                    QPointF(x + w * 0.55 * direction, c.y()),
                    QPointF(x - w * 0.7 * direction, c.y() + h),
                ]
            )
        )
