"""Intrusion pipeline: person / bicycle / motorcycle / horse / sheep / cow.

This module is split from parking so later warning strategies can
diverge. It does not load YOLO or run inference.
"""

from __future__ import annotations

from app.detect import INTRUSION_CLASS_IDS, INTRUSION_NAMES

KIND = "intrusion"


def split_items(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        cls_id = item.get("cls_id")
        name = str(item.get("name") or "")
        if cls_id in INTRUSION_CLASS_IDS or name in INTRUSION_NAMES:
            out.append(item)
    return out
