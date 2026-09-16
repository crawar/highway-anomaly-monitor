"""Save a selected-region screenshot with alert boxes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPen

from app import theme as T
from app.capture import ScreenGrabber
from app.config import AppSettings
from app.detect import LABELS_ZH
from app.hud import _ui_font
from app.paths import ensure_pic_dir


def _next_path(prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = ensure_pic_dir()
    candidate = folder / f"{prefix}{stamp}.png"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        extra = folder / f"{prefix}{stamp}_{n}.png"
        if not extra.exists():
            return extra
        n += 1


def _map_box(xyxy: list[float], src: tuple[int, int], dst: tuple[int, int]) -> QRect:
    iw, ih = src
    ow, oh = dst
    sx = ow / max(1, iw)
    sy = oh / max(1, ih)
    x1, y1, x2, y2 = xyxy
    x = int(round(x1 * sx))
    y = int(round(y1 * sy))
    w = max(1, int(round((x2 - x1) * sx)))
    h = max(1, int(round((y2 - y1) * sy)))
    return QRect(x, y, w, h)


def save_alert_image(
    region: QRect,
    items: list[dict],
    prefix: str,
    image_size: tuple[int, int],
    settings: AppSettings | None = None,
) -> Path | None:
    grabber = ScreenGrabber()
    try:
        bgr = grabber.grab(region)
    finally:
        grabber.close()
    if bgr is None:
        return None

    import numpy as np

    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setFont(_ui_font(11))
    pen = QPen(T.BOX_ALERT, T.BOX_PEN)
    pen.setCosmetic(True)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    src = (max(1, int(image_size[0])), max(1, int(image_size[1])))
    show_labels = bool(settings.show_labels) if settings is not None else False
    for item in items:
        box = _map_box(item.get("xyxy") or [0, 0, 0, 0], src, (w, h))
        if box.width() < 1 or box.height() < 1:
            continue
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(box)
        if not show_labels:
            continue
        conf = float(item.get("conf") or 0.0)
        name = LABELS_ZH.get(str(item.get("name") or ""), str(item.get("name") or ""))
        text = f"{name} {conf:.2f}"
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 4
        label = QRectF(box.x(), box.y() - th - 2, tw, th)
        if label.y() < 0:
            label.moveTop(box.y() + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(T.BOX_LABEL_BG)
        painter.drawRect(label)
        painter.setPen(T.BOX_LABEL)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        still = int(item.get("still") or 0)
        if still > 0:
            count = str(still)
            cw = fm.horizontalAdvance(count) + 10
            below = QRectF(box.x(), box.bottom() + 2, cw, th)
            if below.bottom() > h:
                below.moveBottom(float(box.bottom() - 2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(T.BOX_LABEL_BG)
            painter.drawRect(below)
            painter.setPen(T.BOX_LABEL)
            painter.drawText(below, Qt.AlignmentFlag.AlignCenter, count)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.end()

    path = _next_path(prefix)
    if not image.save(str(path)):
        print(f"Failed to save alert snapshot: {path}")
        return None
    return path
