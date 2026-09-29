"""Alert evaluation: one kind per frame, parking then congestion then intrusion."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, hypot

from app import theme as T
from app.config import AppSettings


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _center(xyxy: list[float]) -> tuple[float, float]:
    return ((xyxy[0] + xyxy[2]) * 0.5, (xyxy[1] + xyxy[3]) * 0.5)


def _diag(xyxy: list[float]) -> float:
    return hypot(xyxy[2] - xyxy[0], xyxy[3] - xyxy[1])


def _is_still(prev: list[float], cur: list[float], iou: float) -> bool:
    if iou >= 0.75:
        return True
    pc = _center(prev)
    cc = _center(cur)
    dist = hypot(pc[0] - cc[0], pc[1] - cc[1])
    return dist < max(8.0, 0.08 * _diag(cur))


def _above(items: list[dict], threshold: float) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if float(item.get("conf") or 0.0) >= threshold:
            out.append(item)
    return out


@dataclass
class Alert:
    intrusion: list[dict] = field(default_factory=list)
    parking: list[dict] = field(default_factory=list)
    congestion: list[dict] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.intrusion or self.parking or self.congestion)

    @property
    def items(self) -> list[dict]:
        if self.parking:
            return list(self.parking)
        if self.congestion:
            return list(self.congestion)
        return list(self.intrusion)

    @property
    def voice_kind(self) -> str | None:
        if self.parking:
            return "parking"
        if self.congestion:
            return "congestion"
        if self.intrusion:
            return "intrusion"
        return None

    @property
    def kinds(self) -> frozenset[str]:
        if self.parking:
            return frozenset({"parking"})
        if self.congestion:
            return frozenset({"congestion"})
        if self.intrusion:
            return frozenset({"intrusion"})
        return frozenset()

    @property
    def prefix(self) -> str:
        if self.parking:
            return "V"
        if self.congestion:
            return "B"
        if self.intrusion:
            return "P"
        return ""

    @property
    def kind_label(self) -> str:
        if self.parking:
            return "违停"
        if self.congestion:
            return "拥堵"
        if self.intrusion:
            return "闯入"
        return ""


@dataclass
class _Track:
    xyxy: list[float]
    still: int = 1
    greens: int = 0
    misses: int = 0


def _high(item: dict, threshold: float) -> bool:
    return float(item.get("conf") or 0.0) >= threshold


@dataclass
class VehicleTracker:
    _tracks: list[_Track] = field(default_factory=list)

    def reset(self) -> None:
        self._tracks = []

    def update(
        self,
        vehicles: list[dict],
        need: int,
        grace: int,
        threshold: float,
    ) -> tuple[bool, list[dict]]:
        need = max(T.MIN_PARKING_FRAMES, int(need))
        grace = max(T.PARKING_GRACE_MIN, min(T.PARKING_GRACE_MAX, int(grace)))
        current = [list(item.get("xyxy") or [0, 0, 0, 0]) for item in vehicles]
        used: set[int] = set()
        next_tracks: list[_Track] = []
        hits: list[dict] = []

        for item, box in zip(vehicles, current):
            item.pop("still", None)
            best_i = -1
            best_iou = 0.3
            for i, track in enumerate(self._tracks):
                if i in used:
                    continue
                iou = _iou(track.xyxy, box)
                if iou > best_iou:
                    best_iou = iou
                    best_i = i
            high = _high(item, threshold)
            if best_i < 0:
                if not high:
                    continue
                track = _Track(box, 1, 0)
                next_tracks.append(track)
                item["still"] = track.still
                if high and track.still >= need:
                    hits.append(item)
                continue
            used.add(best_i)
            prev = self._tracks[best_i]
            if not _is_still(prev.xyxy, box, best_iou):
                if not high:
                    continue
                track = _Track(box, 1, 0)
                next_tracks.append(track)
                item["still"] = track.still
                if high and track.still >= need:
                    hits.append(item)
                continue
            if high:
                track = _Track(box, prev.still + 1, 0)
            else:
                greens = prev.greens + 1
                if greens > grace:
                    continue
                track = _Track(box, prev.still + 1, greens)
            next_tracks.append(track)
            item["still"] = track.still
            if high and track.still >= need:
                hits.append(item)

        for i, prev in enumerate(self._tracks):
            if i in used:
                continue
            misses = prev.misses + 1
            if misses > grace:
                continue
            next_tracks.append(_Track(prev.xyxy, prev.still, 0, misses))

        if len(next_tracks) > T.MAX_PARKING_TRACKS:
            # Keep tracks seen this frame first, then the longest-standing ones;
            # the surplus (freshest / already-missing boxes) is destroyed.
            next_tracks.sort(key=lambda t: (t.misses == 0, t.still), reverse=True)
            del next_tracks[T.MAX_PARKING_TRACKS :]

        self._tracks = next_tracks
        return bool(hits), hits

    def clear_counts(self) -> None:
        """Restart the still-count of every track without losing the boxes.

        Called right after a parking alert fires so the same vehicle has to
        stay put for a full hold period again before it alerts a second time.
        """
        for track in self._tracks:
            track.still = 0
            track.greens = 0


def parking_frames(interval_sec: float, hold_sec: float) -> int:
    interval = max(0.001, float(interval_sec))
    need = ceil(float(hold_sec) / interval - 1e-9)
    return max(T.MIN_PARKING_FRAMES, int(need))


class AlertEngine:
    def __init__(self) -> None:
        self._tracker = VehicleTracker()
        self._congestion_streak = 0

    def reset(self) -> None:
        self._tracker.reset()
        self._congestion_streak = 0

    def evaluate(
        self,
        parking: list[dict],
        intrusion: list[dict],
        settings: AppSettings,
    ) -> Alert:
        result = Alert()
        parking_fired = False
        parking_hits: list[dict] = []
        if settings.parking_alert:
            need = parking_frames(settings.interval_sec, settings.parking_hold_sec)
            parking_fired, parking_hits = self._tracker.update(
                parking,
                need,
                settings.parking_grace_frames,
                settings.parking_conf,
            )
        else:
            self._tracker.reset()

        congestion_fired = False
        congestion_hits: list[dict] = []
        if settings.congestion_alert:
            vehicles = _above(parking, settings.parking_conf)
            if len(vehicles) >= int(settings.congestion_count):
                self._congestion_streak += 1
            else:
                self._congestion_streak = 0
            if self._congestion_streak >= T.CONGESTION_FRAMES:
                congestion_fired = True
                congestion_hits = vehicles
        else:
            self._congestion_streak = 0

        intrusion_hits: list[dict] = []
        if settings.intrusion_alert:
            intrusion_hits = _above(intrusion, settings.intrusion_conf)

        if parking_fired:
            result.parking = parking_hits
        elif congestion_fired:
            result.congestion = congestion_hits
        elif intrusion_hits:
            result.intrusion = intrusion_hits

        if result.active:
            self._tracker.clear_counts()
            self._congestion_streak = 0
        return result
