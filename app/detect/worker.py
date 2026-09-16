"""Single detector process: one YOLO load, then split results by pipeline."""

from __future__ import annotations

import os
import time
from queue import Empty

from app.detect import ALL_CLASS_IDS, COCO_FALLBACK, intrusion, parking
from app.paths import YOLO_HOME, ensure_download_dir


def _parse_items(results) -> list[dict]:
    items: list[dict] = []
    for result in results:
        if result.boxes is None:
            continue
        names = result.names or {}
        for box in result.boxes:
            cls_id = int(box.cls[0])
            if isinstance(names, dict):
                name = names.get(cls_id, names.get(str(cls_id)))
            else:
                name = names[cls_id]
            if not name:
                name = COCO_FALLBACK.get(cls_id, cls_id)
            items.append(
                {
                    "name": str(name),
                    "cls_id": cls_id,
                    "conf": float(box.conf[0]),
                    "xyxy": [float(v) for v in box.xyxy[0].tolist()],
                }
            )
    return items


def _grab_bgr(sct, region: dict):
    import numpy as np

    raw = sct.grab(region)
    arr = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(raw.height, raw.width, 4)
    return np.ascontiguousarray(arr[:, :, :3])


def run(weights: str, ctrl_q, out_q) -> None:
    ensure_download_dir()
    os.environ["YOLO_CONFIG_DIR"] = str(YOLO_HOME)
    os.environ["YOLO_OFFLINE"] = "True"
    os.environ["ULTRALYTICS_OFFLINE"] = "1"

    import mss
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS

    try:
        SETTINGS.update({"sync": False})
    except Exception:
        pass

    model = YOLO(weights)
    sct = mss.mss()
    ids = list(ALL_CLASS_IDS)
    region: dict | None = None
    interval = 1.0
    active = False
    last = 0.0

    try:
        while True:
            try:
                cmd = ctrl_q.get(timeout=0.05)
            except Empty:
                cmd = None
            except Exception:
                break
            if cmd is not None:
                op = cmd.get("op")
                if op == "quit":
                    break
                if op == "stop":
                    active = False
                elif op == "start":
                    region = cmd.get("region")
                    interval = max(0.2, float(cmd.get("interval") or 1.0))
                    active = True
                    last = 0.0
            if not active or not region:
                continue
            now = time.monotonic()
            if now - last < interval:
                continue
            last = now
            try:
                frame = _grab_bgr(sct, region)
                h, w = frame.shape[:2]
                results = model.predict(
                    source=frame,
                    classes=ids,
                    conf=0.05,
                    device="cpu",
                    imgsz=640,
                    verbose=False,
                    max_det=100,
                )
                items = _parse_items(results)
                out_q.put(
                    {
                        "parking": parking.split_items(items),
                        "intrusion": intrusion.split_items(items),
                        "image_size": (w, h),
                    }
                )
            except Exception as exc:
                try:
                    out_q.put(
                        {
                            "parking": [],
                            "intrusion": [],
                            "image_size": (0, 0),
                            "error": str(exc),
                        }
                    )
                except Exception:
                    pass
    finally:
        try:
            sct.close()
        except Exception:
            pass
