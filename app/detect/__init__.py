"""Shared COCO class maps for the two detector pipelines."""

from __future__ import annotations

PARKING_CLASS_IDS = (2, 5, 7)  # car, bus, truck
INTRUSION_CLASS_IDS = (0, 1, 3, 17, 18, 19)  # person, bicycle, motorcycle, horse, sheep, cow
ALL_CLASS_IDS = PARKING_CLASS_IDS + INTRUSION_CLASS_IDS

LABELS_ZH = {
    "person": "人",
    "bicycle": "自行车",
    "motorcycle": "摩托车",
    "horse": "马",
    "sheep": "羊",
    "cow": "牛",
    "car": "小车",
    "bus": "公交车",
    "truck": "卡车",
}

PARKING_NAMES = frozenset({"car", "bus", "truck"})
INTRUSION_NAMES = frozenset({"person", "bicycle", "motorcycle", "horse", "sheep", "cow"})
COCO_FALLBACK = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    17: "horse",
    18: "sheep",
    19: "cow",
}
