"""Send alert snapshots to a DingTalk custom robot webhook."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app import diag
from app.config import AppSettings

log = diag.setup("ui")
_token_cache: dict[str, tuple[str, float]] = {}


def send_alert_async(settings: AppSettings, image_path: Path | str, kind_label: str) -> None:
    if not settings.ding_alert:
        return
    webhook = str(settings.ding_webhook or "").strip()
    if not webhook:
        log.warning("DingTalk alert is on but webhook is empty")
        return
    args = (
        webhook,
        str(settings.ding_secret or "").strip(),
        str(settings.ding_keyword or "").strip(),
        str(settings.ding_app_key or "").strip(),
        str(settings.ding_app_secret or "").strip(),
        str(image_path),
        kind_label,
    )
    thread = threading.Thread(
        target=_send_alert,
        args=args,
        daemon=True,
        name="carfind-dingtalk",
    )
    thread.start()


def _send_alert(
    webhook: str,
    secret: str,
    keyword: str,
    app_key: str,
    app_secret: str,
    image_path: str,
    kind_label: str,
) -> None:
    path = Path(image_path)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    title = f"{kind_label}预警"
    lines = []
    if keyword:
        lines.append(keyword)
        lines.append("")
        title = f"{keyword} {title}"
    lines.append(f"### {kind_label}预警")
    lines.append("")
    lines.append(f"- 时间：{stamp}")
    if path.name:
        lines.append(f"- 截图：{path.name}")
    media_id = _upload_with_app(app_key, app_secret, path)
    if media_id:
        lines.append("")
        lines.append(f"![]({media_id})")
    elif path.is_file() and (app_key or app_secret):
        log.warning("DingTalk image upload failed; sending text only")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": "\n".join(lines),
        },
    }
    try:
        result = _post_json(_signed_url(webhook, secret), payload)
    except Exception as exc:
        log.warning("DingTalk send failed: %s", exc)
        return
    errcode = result.get("errcode", 1)
    if errcode not in (0, None):
        log.warning("DingTalk send rejected: %s", result)
    else:
        log.info("DingTalk sent %s image=%s", path.name, bool(media_id))


def _signed_url(webhook: str, secret: str) -> str:
    if not secret:
        return webhook
    timestamp = str(round(time.time() * 1000))
    signed = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(signed))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def _upload_with_app(app_key: str, app_secret: str, path: Path) -> str:
    if not app_key or not app_secret or not path.is_file():
        return ""
    try:
        token = _app_access_token(app_key, app_secret)
        if not token:
            return ""
        return _upload_media(token, path)
    except Exception as exc:
        log.warning("DingTalk upload failed: %s", exc)
        return ""


def _app_access_token(app_key: str, app_secret: str) -> str:
    now = time.time()
    cached = _token_cache.get(app_key)
    if cached and cached[1] > now:
        return cached[0]
    query = urllib.parse.urlencode({"appkey": app_key, "appsecret": app_secret})
    url = f"https://oapi.dingtalk.com/gettoken?{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("errcode") not in (0, None):
        log.warning("DingTalk token rejected: %s", result.get("errmsg") or result)
        return ""
    token = str(result.get("access_token") or "")
    if not token:
        return ""
    expires = now + max(60.0, float(result.get("expires_in") or 7200) - 120.0)
    _token_cache[app_key] = (token, expires)
    return token


def _upload_media(token: str, path: Path) -> str:
    body, content_type = _multipart_file(path)
    url = (
        "https://oapi.dingtalk.com/media/upload"
        f"?access_token={urllib.parse.quote(token)}&type=image"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("errcode") not in (0, None):
        log.warning("DingTalk media rejected: %s", result.get("errmsg") or result)
        return ""
    media_id = str(result.get("media_id") or "")
    if media_id:
        return media_id
    for key in ("url", "pic_url", "picUrl"):
        value = result.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def _multipart_file(path: Path) -> tuple[bytes, str]:
    boundary = "----CarFindDingTalk"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    raw = path.read_bytes()
    chunks = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="media"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8"),
        raw,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json;charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"errcode": exc.code, "errmsg": raw}
