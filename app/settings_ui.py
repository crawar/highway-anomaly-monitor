"""Metallic settings panel."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QLineEdit, QScrollArea, QWidget

from app import theme as T
from app.alerts import parking_frames
from app.config import load_settings, save_settings
from app.hud import MetalTip, _clamp_to_screen, _paint_metal_panel, _ui_font
from app.win32util import apply_capture_affinity, disable_system_rounding

INTERVAL_TIP = "监视器画面越卡，监视间隔建议越长"
HOLD_TIP = "静止达此时长后报警。按监测间隔向上取整，且至少连续3帧。"
GRACE_TIP = "蓝框之间允许的连续绿框或连续空帧。绿框仍计数，空帧不计数但保留轨迹，超出才清零。"
COOLDOWN_TIP = "同样影响钉钉，仅在不启用“预警后自动打开图片”功能时生效"
DING_HINT = "关键词、加签按钉钉机器人安全设置选填。"
DING_WARN = "不填写Client ID / Secret，钉钉只能发送文字"
DING_HELP_HTML = """
<p style="margin:0 0 10px 0;"><b>如何获取 Client ID / Client Secret</b></p>
<p style="margin:0 0 8px 0;">这不是手机 App，也不用自己搭服务器。只需在钉钉开放平台登记一个「企业内部应用」，拿到一对密钥，本程序才能把预警截图上传到钉钉。</p>
<p style="margin:8px 0 4px 0;"><b>一、先有钉钉企业组织</b></p>
<p style="margin:0 0 8px 0;">必须使用企业/团队组织，不能只用个人聊天。若还没有组织：打开钉钉 App，创建企业或团队，并让自己成为管理员，或请管理员开通开发者后台权限。</p>
<p style="margin:8px 0 4px 0;"><b>二、打开应用中心和开发者后台</b></p>
<p style="margin:0 0 8px 0;">企业应用入口可从钉钉应用中心进入：<br>
<a href="https://appcenter.dingtalk.com/">https://appcenter.dingtalk.com/</a><br>
开发者后台（创建应用、复制密钥）：<br>
<a href="https://open-dev.dingtalk.com/">https://open-dev.dingtalk.com/</a></p>
<p style="margin:8px 0 4px 0;"><b>三、创建企业内部应用</b></p>
<p style="margin:0 0 8px 0;">1. 登录开发者后台，左侧选「应用开发」→「企业内部应用」→「企业应用」。<br>
2. 点右上角「创建应用」。<br>
3. 类型选网页应用 / H5 微应用。不要选小程序，也不要选群里那种自定义机器人。<br>
4. 名称可填 CarFind预警。若要求填写首页地址，可先填 https://www.dingtalk.com（只是占位，不用真做网页）。<br>
5. 保存后进入应用详情。</p>
<p style="margin:8px 0 4px 0;"><b>四、添加能力、复制密钥并发布</b></p>
<p style="margin:0 0 8px 0;">1. 在「添加应用能力」里给「网页应用」点添加。<br>
2. 左侧打开「凭证与基础信息」，复制 Client ID（应用 AppKey）和 Client Secret（应用 AppSecret）。<br>
3. 打开最下方「版本管理与发布」，发布当前版本。不发布则接口不生效。<br>
4. 把两项密钥填回本程序「钉钉」页。</p>
<p style="margin:8px 0 4px 0;"><b>五、和群机器人不是同一个人，行不行</b></p>
<p style="margin:0 0 8px 0;">可以。Client ID / Secret 来自企业内部应用，Webhook 来自某个群的自定义机器人，创建者不必是同一个钉钉用户。<br>
约束：应用和群必须属于同一个钉钉组织。跨公司、跨组织无法用来发图。<br>
群机器人在钉钉群 → 群设置 → 智能群助手 → 添加自定义机器人中创建，并复制 Webhook。安全设置可按需打开自定义关键词、加签。</p>
<p style="margin:8px 0 0 0;"><b>六、不填密钥会怎样</b></p>
<p style="margin:0;">Webhook 仍可发文字预警。不填写 Client ID / Secret 时，钉钉只能发送文字，群里看不到截图。</p>
"""

_EDIT_STYLE = """
QLineEdit {
    background: rgba(8, 9, 11, 200);
    color: #e2e6ec;
    border: 1px solid rgba(168, 174, 182, 90);
    border-radius: 6px;
    padding: 3px 8px;
    selection-background-color: #2f7ec8;
}
QLineEdit:focus {
    border: 1px solid rgba(56, 168, 255, 160);
}
"""


def _mix(a: float, lo: float, hi: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, a))


def _t_of(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _interval_t(value: float) -> float:
    steps = T.INTERVAL_STEPS
    idx = min(range(len(steps)), key=lambda i: abs(steps[i] - value))
    return idx / (len(steps) - 1)


def _cooldown_t(value: float) -> float:
    steps = T.COOLDOWN_STEPS
    idx = min(range(len(steps)), key=lambda i: abs(steps[i] - value))
    return idx / (len(steps) - 1)


def _fmt_cooldown(value: int) -> str:
    sec = int(value)
    if sec % 60 == 0:
        return f"{sec // 60}m"
    if sec > 60:
        return f"{sec / 60:.1f}m"
    return f"{sec}s"


def _fmt_interval(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value))}s"
    return f"{value:.1f}s"


class SettingsPanel(QWidget):
    changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(T.SETTINGS_W, T.SETTINGS_H)
        self.setFont(_ui_font(12))
        self.setMouseTracking(True)
        self._settings = load_settings()
        self._tab = "main"
        self._help_open = False
        self._drag: str | None = None
        self._hover = ""
        self._chrome_ready = False
        groove_w = self.width() - 146
        self._tab_main = QRect(self.width() - 18 - 56 - 8 - 52, 8, 52, 26)
        self._tab_ding = QRect(self.width() - 18 - 56, 8, 56, 26)
        self._sliders = {
            "interval": QRect(126, 52, groove_w, 16),
            "hold": QRect(126, 94, groove_w, 16),
            "grace": QRect(126, 136, groove_w, 16),
            "parking": QRect(126, 178, groove_w, 16),
            "intrusion": QRect(126, 220, groove_w, 16),
            "cooldown": QRect(126, 262, groove_w, 16),
        }
        self._checks = {
            "show_labels": QRect(18, 308, 18, 18),
            "intrusion_alert": QRect(158, 308, 18, 18),
            "parking_alert": QRect(18, 338, 18, 18),
            "voice_alert": QRect(158, 338, 18, 18),
            "debug_mode": QRect(18, 368, 18, 18),
            "gaze_guidance": QRect(158, 368, 18, 18),
            "auto_open_image": QRect(18, 398, 18, 18),
        }
        self._check_labels = {
            "show_labels": "显示标签",
            "intrusion_alert": "闯入报警",
            "parking_alert": "违停报警",
            "voice_alert": "语音播报",
            "debug_mode": "调试模式",
            "auto_open_image": "预警后自动打开图片",
            "gaze_guidance": "视线引导",
        }
        self._ding_check = QRect(18, 48, 18, 18)
        self._btn_help = QRect(self.width() - 18 - 92, 46, 92, 26)
        self._fields = {
            "ding_app_key": {
                "label": "Client ID",
                "label_rect": QRect(18, 78, 180, 18),
                "edit": QRect(18, 98, self.width() - 64, 28),
                "eye": QRect(self.width() - 42, 100, 24, 24),
            },
            "ding_app_secret": {
                "label": "Client Secret",
                "label_rect": QRect(18, 136, 180, 18),
                "edit": QRect(18, 156, self.width() - 64, 28),
                "eye": QRect(self.width() - 42, 158, 24, 24),
            },
            "ding_keyword": {
                "label": "自定义关键词",
                "label_rect": QRect(18, 194, 180, 18),
                "edit": QRect(18, 214, self.width() - 64, 28),
                "eye": QRect(self.width() - 42, 216, 24, 24),
            },
            "ding_secret": {
                "label": "加签",
                "label_rect": QRect(18, 252, 180, 18),
                "edit": QRect(18, 272, self.width() - 64, 28),
                "eye": QRect(self.width() - 42, 274, 24, 24),
            },
            "ding_webhook": {
                "label": "Webhook",
                "label_rect": QRect(18, 310, 180, 18),
                "edit": QRect(18, 330, self.width() - 64, 28),
                "eye": QRect(self.width() - 42, 332, 24, 24),
            },
        }
        self._reveal = {key: False for key in self._fields}
        self._edits: dict[str, QLineEdit] = {}
        for key, spec in self._fields.items():
            edit = QLineEdit(self)
            edit.setGeometry(spec["edit"])
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setFont(_ui_font(11))
            edit.setStyleSheet(_EDIT_STYLE)
            edit.setVisible(False)
            edit.setPlaceholderText(spec["label"])
            if key in ("ding_app_key", "ding_app_secret"):
                edit.textChanged.connect(self.update)
            self._edits[key] = edit
        self._help_scroll = QScrollArea(self)
        self._help_scroll.setGeometry(14, 80, self.width() - 28, self.height() - 140)
        self._help_scroll.setWidgetResizable(True)
        self._help_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._help_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._help_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 8px; background: rgba(8,9,11,80); }"
            "QScrollBar::handle:vertical { background: rgba(168,174,182,90); border-radius: 4px; }"
        )
        help_label = QLabel()
        help_label.setWordWrap(True)
        help_label.setOpenExternalLinks(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        help_label.setText(DING_HELP_HTML)
        help_label.setFont(_ui_font(11))
        help_label.setStyleSheet("QLabel { color: #e2e6ec; background: transparent; }")
        self._help_scroll.setWidget(help_label)
        self._help_scroll.hide()
        self._btn_cancel = QRect(18, self.height() - 48, 122, 30)
        self._btn_save = QRect(self.width() - 140, self.height() - 48, 122, 30)
        self._tip = MetalTip(self)

    def popup_above(self, home: QRect) -> None:
        self._settings = replace(load_settings())
        self._tab = "main"
        self._help_open = False
        self._drag = None
        self._hover = ""
        self._reveal = {key: False for key in self._fields}
        self._sync_edits_from_settings()
        self._apply_tab()
        self._tip.hide()
        x = home.center().x() - self.width() // 2
        y = home.top() - self.height() - 8
        pos = _clamp_to_screen(QPoint(x, y), self.width(), self.height())
        self.move(pos)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_ready:
            disable_system_rounding(self)
            self._chrome_ready = True
        apply_capture_affinity(self)

    def hideEvent(self, event) -> None:
        self._tip.hide()
        self._help_scroll.hide()
        super().hideEvent(event)

    def _sync_edits_from_settings(self) -> None:
        for key in self._fields:
            edit = self._edits[key]
            edit.setText(str(getattr(self._settings, key) or ""))
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._reveal[key] = False

    def _read_edits_to_settings(self) -> None:
        for key in self._fields:
            setattr(self._settings, key, self._edits[key].text().strip())

    def _apply_tab(self) -> None:
        show_fields = self._tab == "ding" and not self._help_open
        for edit in self._edits.values():
            edit.setVisible(show_fields)
        self._help_scroll.setVisible(self._tab == "ding" and self._help_open)
        if self._tab != "ding" or not self._help_open:
            self.setFocus()
        self.update()

    def _missing_app_creds(self) -> bool:
        key = self._edits["ding_app_key"].text().strip()
        secret = self._edits["ding_app_secret"].text().strip()
        return not key or not secret

    def _save(self) -> None:
        self._read_edits_to_settings()
        self._settings.clamp()
        if self._settings.ding_alert:
            webhook = self._settings.ding_webhook
            if not webhook:
                self._tab = "ding"
                self._apply_tab()
                self._show_ding_tip("请填写Webhook", "ding_webhook")
                return
            if not (webhook.startswith("http://") or webhook.startswith("https://")):
                self._tab = "ding"
                self._apply_tab()
                self._show_ding_tip("Webhook 格式不正确", "ding_webhook")
                return
        save_settings(self._settings)
        self.changed.emit(self._settings)
        self.hide()

    def _cancel(self) -> None:
        self.hide()

    def _show_ding_tip(self, text: str, field: str = "ding_webhook") -> None:
        box = self._fields[field]["edit"]
        top_left = self.mapToGlobal(box.topLeft())
        self._tip.popup(text, QRect(top_left, box.size()))

    def _slider_value(self, key: str, x: int) -> None:
        groove = self._sliders[key]
        t = _t_of(float(x), float(groove.left()), float(groove.right()))
        if key == "interval":
            last = len(T.INTERVAL_STEPS) - 1
            idx = int(round(t * last))
            self._settings.interval_sec = T.INTERVAL_STEPS[max(0, min(last, idx))]
        elif key == "hold":
            self._settings.parking_hold_sec = int(
                round(_mix(t, float(T.PARKING_HOLD_MIN), float(T.PARKING_HOLD_MAX)))
            )
        elif key == "grace":
            last = T.PARKING_GRACE_MAX - T.PARKING_GRACE_MIN
            idx = int(round(t * last))
            self._settings.parking_grace_frames = T.PARKING_GRACE_MIN + max(0, min(last, idx))
        elif key == "parking":
            self._settings.parking_conf = round(_mix(t, 0.05, 0.95), 2)
        elif key == "intrusion":
            self._settings.intrusion_conf = round(_mix(t, 0.05, 0.95), 2)
        elif key == "cooldown":
            last = len(T.COOLDOWN_STEPS) - 1
            idx = int(round(t * last))
            self._settings.cooldown_sec = T.COOLDOWN_STEPS[max(0, min(last, idx))]
        self._settings.clamp()
        if key == "interval":
            self._show_interval_tip()
        elif key == "hold":
            self._show_hold_tip()
        elif key == "grace":
            self._show_grace_tip()
        elif key == "cooldown":
            self._show_cooldown_tip()
        self.update()

    def _slider_area(self, key: str) -> QRect:
        groove = self._sliders[key]
        return QRect(12, groove.y() - 16, self.width() - 24, 36)

    def _check_hit(self, key: str, pos) -> bool:
        box = self._checks[key]
        extra = 240 if key == "auto_open_image" else 112
        return box.adjusted(-4, -4, extra, 4).contains(pos)

    def _ding_check_hit(self, pos) -> bool:
        return self._ding_check.adjusted(-4, -4, 120, 4).contains(pos)

    def _show_interval_tip(self) -> None:
        top_left = self.mapToGlobal(self._slider_area("interval").topLeft())
        self._tip.popup(INTERVAL_TIP, QRect(top_left, self._slider_area("interval").size()))

    def _show_hold_tip(self) -> None:
        frames = parking_frames(self._settings.interval_sec, self._settings.parking_hold_sec)
        text = f"{HOLD_TIP}当前约 {frames} 帧。"
        top_left = self.mapToGlobal(self._slider_area("hold").topLeft())
        self._tip.popup(text, QRect(top_left, self._slider_area("hold").size()))

    def _show_grace_tip(self) -> None:
        top_left = self.mapToGlobal(self._slider_area("grace").topLeft())
        self._tip.popup(GRACE_TIP, QRect(top_left, self._slider_area("grace").size()))

    def _show_cooldown_tip(self) -> None:
        top_left = self.mapToGlobal(self._slider_area("cooldown").topLeft())
        self._tip.popup(COOLDOWN_TIP, QRect(top_left, self._slider_area("cooldown").size()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._tab_main.contains(pos):
                self._tab = "main"
                self._help_open = False
                self._tip.hide()
                self._apply_tab()
                event.accept()
                return
            if self._tab_ding.contains(pos):
                self._tab = "ding"
                self._help_open = False
                self._tip.hide()
                self._apply_tab()
                event.accept()
                return
            if self._btn_save.contains(pos):
                self._save()
                event.accept()
                return
            if self._btn_cancel.contains(pos):
                self._cancel()
                event.accept()
                return
            if self._tab == "ding":
                if self._btn_help.contains(pos):
                    self._help_open = not self._help_open
                    self._tip.hide()
                    self._apply_tab()
                    event.accept()
                    return
                if self._help_open:
                    event.accept()
                    return
                if self._ding_check_hit(pos):
                    self._settings.ding_alert = not self._settings.ding_alert
                    self.update()
                    event.accept()
                    return
                for key, spec in self._fields.items():
                    if spec["eye"].contains(pos):
                        self._reveal[key] = not self._reveal[key]
                        mode = (
                            QLineEdit.EchoMode.Normal
                            if self._reveal[key]
                            else QLineEdit.EchoMode.Password
                        )
                        self._edits[key].setEchoMode(mode)
                        self.update()
                        event.accept()
                        return
                event.accept()
                return
            for key in self._checks:
                if self._check_hit(key, pos):
                    cur = bool(getattr(self._settings, key))
                    setattr(self._settings, key, not cur)
                    self.update()
                    event.accept()
                    return
            for key, rect in self._sliders.items():
                hit = QRect(rect.x() - 8, rect.y() - 8, rect.width() + 16, rect.height() + 16)
                if hit.contains(pos):
                    self._drag = key
                    self._slider_value(key, pos.x())
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._slider_value(self._drag, pos.x())
            return
        hover = ""
        if self._btn_save.contains(pos):
            hover = "save"
        elif self._btn_cancel.contains(pos):
            hover = "cancel"
        elif self._tab_main.contains(pos):
            hover = "tab_main"
        elif self._tab_ding.contains(pos):
            hover = "tab_ding"
        elif self._tab == "main" and self._slider_area("interval").contains(pos):
            hover = "interval"
        elif self._tab == "main" and self._slider_area("hold").contains(pos):
            hover = "hold"
        elif self._tab == "main" and self._slider_area("grace").contains(pos):
            hover = "grace"
        elif self._tab == "main" and self._slider_area("cooldown").contains(pos):
            hover = "cooldown"
        elif self._tab == "ding" and self._btn_help.contains(pos):
            hover = "help"
        elif self._tab == "ding" and not self._help_open and self._ding_check_hit(pos):
            hover = "ding_alert"
        elif self._tab == "ding" and not self._help_open:
            for key, spec in self._fields.items():
                if spec["eye"].contains(pos):
                    hover = f"eye_{key}"
                    break
        elif self._tab == "main":
            for key in self._checks:
                if self._check_hit(key, pos):
                    hover = key
                    break
        if hover != self._hover:
            self._hover = hover
            if hover == "interval":
                self._show_interval_tip()
            elif hover == "hold":
                self._show_hold_tip()
            elif hover == "grace":
                self._show_grace_tip()
            elif hover == "cooldown":
                self._show_cooldown_tip()
            else:
                self._tip.hide()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "show_exit_popup"):
            parent.show_exit_popup(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        _paint_metal_panel(p, body, 16.0)
        p.setFont(_ui_font(13))
        p.setPen(T.SETTINGS_TEXT)
        p.drawText(QRect(18, 10, 80, 22), Qt.AlignmentFlag.AlignVCenter, "设置")
        self._paint_tab(p, self._tab_main, "主要", self._tab == "main", self._hover == "tab_main")
        self._paint_tab(p, self._tab_ding, "钉钉", self._tab == "ding", self._hover == "tab_ding")

        if self._tab == "main":
            self._paint_main(p)
        elif self._help_open:
            self._paint_button(p, self._btn_help, "返回", self._hover == "help")
        else:
            self._paint_ding(p)

        self._paint_button(p, self._btn_cancel, "取消", self._hover == "cancel")
        self._paint_button(p, self._btn_save, "保存", self._hover == "save")

    def _paint_main(self, p: QPainter) -> None:
        self._paint_slider(
            p, "监测间隔", _fmt_interval(self._settings.interval_sec),
            self._sliders["interval"], _interval_t(self._settings.interval_sec),
        )
        self._paint_slider(
            p, "违停时间", f"{self._settings.parking_hold_sec}s",
            self._sliders["hold"],
            _t_of(float(self._settings.parking_hold_sec), float(T.PARKING_HOLD_MIN), float(T.PARKING_HOLD_MAX)),
        )
        self._paint_slider(
            p, "违停宽限帧", f"{self._settings.parking_grace_frames}帧",
            self._sliders["grace"],
            _t_of(
                float(self._settings.parking_grace_frames),
                float(T.PARKING_GRACE_MIN),
                float(T.PARKING_GRACE_MAX),
            ),
        )
        self._paint_slider(
            p, "违停置信度", f"{self._settings.parking_conf:.2f}",
            self._sliders["parking"], _t_of(self._settings.parking_conf, 0.05, 0.95),
        )
        self._paint_slider(
            p, "闯入置信度", f"{self._settings.intrusion_conf:.2f}",
            self._sliders["intrusion"], _t_of(self._settings.intrusion_conf, 0.05, 0.95),
        )
        self._paint_slider(
            p, "报警冷却", _fmt_cooldown(self._settings.cooldown_sec),
            self._sliders["cooldown"],
            _cooldown_t(self._settings.cooldown_sec),
        )
        for key, rect in self._checks.items():
            label_w = 240 if key == "auto_open_image" else 110
            self._paint_check(
                p, rect, bool(getattr(self._settings, key)),
                self._check_labels[key], self._hover == key, label_w,
            )

    def _paint_ding(self, p: QPainter) -> None:
        self._paint_check(
            p,
            self._ding_check,
            self._settings.ding_alert,
            "启动钉钉报警",
            self._hover == "ding_alert",
            180,
        )
        for key, spec in self._fields.items():
            p.setFont(_ui_font(12))
            p.setPen(T.SETTINGS_TEXT)
            suffix = " *" if key == "ding_webhook" else ""
            p.drawText(spec["label_rect"], Qt.AlignmentFlag.AlignVCenter, spec["label"] + suffix)
            self._paint_eye(p, spec["eye"], self._reveal[key], self._hover == f"eye_{key}")
        self._paint_button(p, self._btn_help, "获取方法", self._hover == "help")
        if self._missing_app_creds():
            p.setFont(_ui_font(11))
            p.setPen(T.BOX_ALERT)
            p.drawText(
                QRect(18, 364, self.width() - 36, 36),
                Qt.AlignmentFlag.AlignTop
                | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap,
                DING_WARN,
            )
        p.setFont(_ui_font(11))
        p.setPen(T.SETTINGS_MUTED)
        p.drawText(
            QRect(18, 400, self.width() - 36, 36),
            Qt.AlignmentFlag.AlignTop
            | Qt.AlignmentFlag.AlignLeft
            | Qt.TextFlag.TextWordWrap,
            DING_HINT,
        )

    def _paint_tab(self, p: QPainter, rect: QRect, title: str, active: bool, hover: bool) -> None:
        body = QRectF(rect)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if active:
            fill.setColorAt(0.0, QColor(92, 98, 108))
            fill.setColorAt(1.0, QColor(38, 41, 46))
        elif hover:
            fill.setColorAt(0.0, QColor(80, 86, 94))
            fill.setColorAt(1.0, QColor(32, 34, 38))
        else:
            fill.setColorAt(0.0, QColor(58, 62, 68))
            fill.setColorAt(1.0, QColor(24, 26, 30))
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(body, 8.0, 8.0)
        p.setPen(T.SETTINGS_TEXT if active or hover else T.SETTINGS_MUTED)
        p.setFont(_ui_font(12))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)

    def _paint_eye(self, p: QPainter, rect: QRect, opened: bool, hover: bool) -> None:
        cx, cy = rect.center().x(), rect.center().y()
        color = T.SETTINGS_TEXT if opened or hover else T.SETTINGS_MUTED
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.4))
        p.drawEllipse(QRectF(cx - 8, cy - 5, 16, 10))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - 2.2, cy - 2.2, 4.4, 4.4))
        if not opened:
            p.setPen(QPen(color, 1.5))
            p.drawLine(rect.left() + 4, rect.bottom() - 6, rect.right() - 4, rect.top() + 6)

    def _paint_check(
        self, p: QPainter, rect: QRect, on: bool, title: str, hover: bool, label_w: int = 180
    ) -> None:
        box = QRectF(rect)
        p.setPen(QPen(T.WINDOW_RIM, 1.1))
        p.setBrush(QColor(255, 255, 255, 22 if hover else 12))
        p.drawRoundedRect(box, 4.0, 4.0)
        if on:
            p.setPen(QPen(T.ICON_GREEN, 1.8))
            p.drawLine(int(box.x() + 4), int(box.center().y()), int(box.x() + 7), int(box.bottom() - 4))
            p.drawLine(int(box.x() + 7), int(box.bottom() - 4), int(box.right() - 4), int(box.y() + 4))
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(12))
        p.drawText(
            QRect(rect.right() + 8, rect.y() - 2, label_w, 22),
            Qt.AlignmentFlag.AlignVCenter,
            title,
        )

    def _paint_button(self, p: QPainter, rect: QRect, title: str, hover: bool) -> None:
        body = QRectF(rect)
        p.setPen(QPen(T.WINDOW_RIM, 1.0))
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        if hover:
            fill.setColorAt(0.0, QColor(92, 98, 108))
            fill.setColorAt(1.0, QColor(38, 41, 46))
        else:
            fill.setColorAt(0.0, QColor(72, 76, 84))
            fill.setColorAt(1.0, QColor(28, 30, 34))
        p.setBrush(fill)
        p.drawRoundedRect(body, 8.0, 8.0)
        p.setPen(T.SETTINGS_TEXT)
        p.setFont(_ui_font(12))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)

    def _paint_slider(
        self, p: QPainter, title: str, value: str, groove: QRect, t: float
    ) -> None:
        p.setFont(_ui_font(12))
        p.setPen(T.SETTINGS_TEXT)
        p.drawText(QRect(18, groove.y() - 12, 108, 18), Qt.AlignmentFlag.AlignVCenter, title)
        p.setPen(T.SETTINGS_MUTED)
        p.setFont(_ui_font(11))
        p.drawText(
            QRect(18, groove.y() + 4, 108, 16),
            Qt.AlignmentFlag.AlignVCenter,
            value,
        )
        gy = groove.center().y()
        track = QRectF(groove.x(), gy - 2, groove.width(), 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 9, 11, 180))
        p.drawRoundedRect(track, 2.0, 2.0)
        fill = QRectF(track)
        fill.setWidth(max(4.0, track.width() * t))
        grad = QLinearGradient(fill.topLeft(), fill.topRight())
        grad.setColorAt(0.0, QColor(90, 160, 220))
        grad.setColorAt(1.0, QColor(56, 168, 255))
        p.setBrush(grad)
        p.drawRoundedRect(fill, 2.0, 2.0)
        hx = track.x() + track.width() * t
        handle = QRectF(hx - 7, gy - 7, 14, 14)
        hg = QLinearGradient(handle.topLeft(), handle.bottomLeft())
        hg.setColorAt(0.0, QColor(210, 216, 224))
        hg.setColorAt(1.0, QColor(86, 92, 100))
        p.setBrush(hg)
        p.setPen(QPen(QColor(230, 235, 240, 80), 1.0))
        p.drawEllipse(handle)
