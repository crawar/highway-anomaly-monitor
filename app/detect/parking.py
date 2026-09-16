"""Illegal-parking pipeline: car / truck / bus.

This module is split from intrusion so later warning strategies can
diverge. It does not load YOLO or run inference.
"""

from __future__ import annotations

from app.detect import PARKING_CLASS_IDS, PARKING_NAMES

KIND = "parking"


def split_items(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        cls_id = item.get("cls_id")
        name = str(item.get("name") or "")
        if cls_id in PARKING_CLASS_IDS or name in PARKING_NAMES:
            out.append(item)
    return out
