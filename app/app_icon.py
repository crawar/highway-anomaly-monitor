"""Application icon: a white line-art eye inside a pale-blue circle."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def create_app_icon(size: int = 256) -> QIcon:
    side = max(32, int(size))
    scale = side / 256.0
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(scale, scale)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#73C7F2"))
    painter.drawEllipse(QPointF(128.0, 128.0), 104.0, 104.0)

    eye = QPainterPath()
    eye.moveTo(66.0, 128.0)
    eye.cubicTo(96.0, 88.0, 160.0, 88.0, 190.0, 128.0)
    eye.cubicTo(160.0, 168.0, 96.0, 168.0, 66.0, 128.0)
    eye_pen = QPen(QColor("#FFFFFF"), 14.0)
    eye_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    eye_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(eye_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(eye)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(QPointF(128.0, 128.0), 18.0, 18.0)
    painter.end()

    return QIcon(pixmap)
