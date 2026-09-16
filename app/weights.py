"""Download YOLO26 large COCO weights into the project Download folder."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from app.paths import (
    WEIGHTS_FILE,
    WEIGHTS_MIN_BYTES,
    WEIGHTS_NAME,
    WEIGHTS_URL,
    ensure_download_dir,
)


def weights_ready(path: Path | None = None) -> bool:
    target = path or WEIGHTS_FILE
    try:
        return target.is_file() and target.stat().st_size >= WEIGHTS_MIN_BYTES
    except OSError:
        return False


def download_weights(dest: Path | None = None) -> Path:
    ensure_download_dir()
    target = dest or WEIGHTS_FILE
    if weights_ready(target):
        print(f"Weights already present: {target}")
        return target

    tmp = target.with_suffix(target.suffix + ".part")
    print(f"Downloading {WEIGHTS_NAME}")
    print(f"From {WEIGHTS_URL}")
    print(f"Into {target}")

    request = urllib.request.Request(
        WEIGHTS_URL,
        headers={"User-Agent": "CarFind-YOLO26-Downloader"},
    )
    with urllib.request.urlopen(request, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        copied = 0
        chunk = 1024 * 256
        last_pct = -1
        with tmp.open("wb") as out:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                out.write(buf)
                copied += len(buf)
                if total > 0:
                    pct = int(copied * 100 / total)
                    if pct != last_pct and pct % 5 == 0:
                        print(f"Progress {pct}% ({copied}/{total} bytes)")
                        last_pct = pct
                elif copied % (1024 * 1024 * 5) < chunk:
                    print(f"Downloaded {copied} bytes")

    if copied < WEIGHTS_MIN_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download too small: {copied} bytes")

    tmp.replace(target)
    print(f"Saved {target} ({copied} bytes)")
    return target


def main() -> int:
    try:
        download_weights()
    except Exception as exc:
        print(f"Failed to download weights: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
