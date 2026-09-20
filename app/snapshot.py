"""Save a selected-region screenshot with alert boxes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from app import diag, theme as T
from app.capture import ScreenGrabber
from app.config import AppSettings
from app.detect import LABELS_ZH
from app.hud import _ui_font
from app.paths import ensure_pic_dir

log = diag.setup("ui")


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


def _item_color(item: dict, threshold: float, alert_ids: set[int]) -> QColor:
    if id(item) in alert_ids:
        return T.BOX_ALERT
    conf = float(item.get("conf") or 0.0)
    return T.BOX_HIGH if conf >= threshold else T.BOX_LOW


def _draw_item(
    painter: QPainter,
    item: dict,
    color: QColor,
    src: tuple[int, int],
    dst: tuple[int, int],
    image_h: int,
    show_labels: bool,
) -> None:
    box = _map_box(item.get("xyxy") or [0, 0, 0, 0], src, dst)
    if box.width() < 1 or box.height() < 1:
        return
    pen = QPen(color, T.BOX_PEN)
    pen.setCosmetic(True)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(box)
    if not show_labels:
        return
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
        if below.bottom() > image_h:
            below.moveBottom(float(box.bottom() - 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(T.BOX_LABEL_BG)
        painter.drawRect(below)
        painter.setPen(T.BOX_LABEL)
        painter.drawText(below, Qt.AlignmentFlag.AlignCenter, count)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)


def save_alert_image(
    region: QRect,
    items: list[dict],
    prefix: str,
    image_size: tuple[int, int],
    settings: AppSettings | None = None,
    parking: list[dict] | None = None,
    intrusion: list[dict] | None = None,
) -> Path | None:
    grabber = ScreenGrabber()
    try:
        bgr = grabber.grab(region)
    finally:
        grabber.close()
    if bgr is None:
        log.warning("alert snapshot: screen grab returned nothing for %s", region)
        return None

    import numpy as np

    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setFont(_ui_font(11))
    src = (max(1, int(image_size[0])), max(1, int(image_size[1])))
    dst = (w, h)
    show_labels = bool(settings.show_labels) if settings is not None else False
    debug = bool(settings.debug_mode) if settings is not None else False
    alert_ids = {id(item) for item in items}
    if debug:
        parking_conf = float(settings.parking_conf) if settings is not None else T.DEFAULT_CONF
        intrusion_conf = (
            float(settings.intrusion_conf) if settings is not None else T.DEFAULT_INTRUSION_CONF
        )
        for item in parking or []:
            _draw_item(
                painter,
                item,
                _item_color(item, parking_conf, alert_ids),
                src,
                dst,
                h,
                show_labels,
            )
        for item in intrusion or []:
            _draw_item(
                painter,
                item,
                _item_color(item, intrusion_conf, alert_ids),
                src,
                dst,
                h,
                show_labels,
            )
    else:
        for item in items:
            _draw_item(painter, item, T.BOX_ALERT, src, dst, h, show_labels)
    painter.end()

    # Store alert geometry inside the PNG itself. This keeps each record as a
    # single portable image while allowing the viewer to guide attention.
    alert_boxes: list[list[int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for item in items:
        box = _map_box(item.get("xyxy") or [0, 0, 0, 0], src, dst)
        if box.width() < 1 or box.height() < 1:
            continue
        coords = (box.x(), box.y(), box.width(), box.height())
        if coords in seen:
            continue
        seen.add(coords)
        alert_boxes.append(list(coords))
    image.setText(T.ALERT_BOX_METADATA_KEY, json.dumps(alert_boxes, separators=(",", ":")))

    path = _next_path(prefix)
    if not image.save(str(path)):
        log.error("Failed to save alert snapshot: %s", path)
        return None
    return path
