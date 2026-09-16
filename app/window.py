"""Tiny metallic HUD homepage window."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app import VERSION, theme as T
from app.alerts import Alert, AlertEngine
from app.buttons import MetalButton
from app.hud import ExitPopup, MetalTip
from app.list_ui import AlertListWindow
from app.overlay import OverlayWindow
from app.paths import (
    WEIGHTS_FILE,
    ensure_download_dir,
    ensure_pic_dir,
)
from app.picker import RegionPicker, virtual_desktop
from app.runtime import DetectRuntime
from app.dingtalk import send_alert_async
from app.settings_ui import SettingsPanel
from app.snapshot import save_alert_image
from app.sound import VoicePlayer
from app.config import load_settings
from app.win32util import (
    apply_capture_affinity,
    capture_hidden,
    disable_system_rounding,
    set_demo_capture,
)
from app.weights import weights_ready


TIPS = {
    "play": "启动/停止",
    "select": "监视区域",
    "list": "预警列表",
    "settings": "设置",
    "collapse": "折叠",
}


class HomeWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"CarFind {VERSION}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # The native window keeps a constant size forever. Any resize or
        # move+resize of a layered window lets DWM briefly present the old
        # backing store at the new geometry (ghost buttons / shifted edge).
        # Collapsing is purely a paint-level effect: the capsule shrinks
        # inside the window and the vacated area is fully transparent,
        # which Windows treats as click-through for layered windows.
        self.setFixedSize(T.EXPANDED_W, T.WIN_H)

        self._t = 0.0
        self._target_collapsed = False
        self._drag_offset: QPoint | None = None
        self._win_round_applied = False
        self._running = False
        self.monitor_region: QRect | None = None
        self._picker: RegionPicker | None = None
        self._tip_btn: MetalButton | None = None
        self._alerting = False
        self._shot_cool = False
        self._shot_kinds: frozenset[str] = frozenset()
        self._list_was_running = False
        self._alert = AlertEngine()
        self._voice = VoicePlayer(self)

        ensure_pic_dir()
        ensure_download_dir()

        self.btn_play = MetalButton("play", self)
        self.btn_select = MetalButton("select", self)
        self.btn_list = MetalButton("list", self)
        self.btn_settings = MetalButton("settings", self)
        self.btn_collapse = MetalButton("collapse", self)

        # Buttons that fade out when collapsed; list stays visible.
        self._mid_buttons = (self.btn_select, self.btn_settings)
        # List stays usable while running so alert images can be opened
        # from the collapsed capsule.
        self._lock_buttons = (self.btn_select, self.btn_settings)
        self._all_buttons = (
            self.btn_play,
            self.btn_select,
            self.btn_list,
            self.btn_settings,
            self.btn_collapse,
        )

        self._anim = QPropertyAnimation(self, b"collapse_t", self)
        self._anim.setDuration(T.COLLAPSE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._tip = MetalTip(self)
        self._exit_popup = ExitPopup(self)
        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.setInterval(T.TIP_DELAY_MS)
        self._tip_timer.timeout.connect(self._show_tip)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(T.REGION_HINT_MS)
        self._hint_timer.timeout.connect(self._hide_tip)
        self._cooldown = QTimer(self)
        self._cooldown.setSingleShot(True)
        self._cooldown.timeout.connect(self._on_cooldown_end)

        self._overlay = OverlayWindow()
        self._runtime = DetectRuntime(self)
        self._settings_panel = SettingsPanel(self)
        self._list_panel = AlertListWindow(self)
        set_demo_capture(load_settings().demo_record)
        self._overlay.apply_settings(load_settings())

        self._runtime.scene_ready.connect(self._on_scene_ready)
        self._settings_panel.changed.connect(self._on_settings_changed)
        self._list_panel.closed.connect(self._on_list_closed)
        self._runtime.prepare()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

        self.btn_collapse.clicked.connect(self.toggle_collapse)
        self.btn_play.clicked.connect(self._on_play_clicked)
        self.btn_select.clicked.connect(self._on_select_clicked)
        self.btn_list.clicked.connect(self._on_list_clicked)
        self.btn_settings.clicked.connect(self._on_settings_clicked)

        for btn in self._all_buttons:
            btn.hover_entered.connect(lambda b=btn: self._on_btn_hover(b))
            btn.hover_left.connect(self._on_btn_leave)

        self.btn_list.raise_()
        self.btn_play.raise_()
        self.btn_collapse.raise_()

        self._layout_buttons()

    def get_collapse_t(self) -> float:
        return self._t

    def set_collapse_t(self, value: float) -> None:
        self._t = max(0.0, min(1.0, value))
        self.btn_collapse.set_fold(self._t)
        fade = max(0.0, 1.0 - self._t * 1.85)
        for btn in self._mid_buttons:
            btn.set_face_opacity(fade)
        self._layout_buttons()
        if self._tip_btn is not None and (
            not self._tip_btn.isVisible() or self._tip_btn._face_opacity < 0.45
        ):
            self._hide_tip()
        self.update()

    collapse_t = Property(float, get_collapse_t, set_collapse_t)

    def _body_width(self) -> int:
        return round(T.EXPANDED_W + (T.COLLAPSED_W - T.EXPANDED_W) * self._t)

    def _body_offset(self) -> int:
        """Horizontal gap between the window's left edge and the capsule."""
        return max(0, self.width() - self._body_width())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._win_round_applied:
            disable_system_rounding(self)
            self._win_round_applied = True
        self._apply_capture_affinity()

    def _set_collapsed(self, collapsed: bool) -> None:
        if self._target_collapsed == collapsed:
            if collapsed and self._t >= 0.999:
                return
            if not collapsed and self._t <= 0.001:
                return
        self._target_collapsed = collapsed
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if collapsed else 0.0)
        self._anim.start()

    def toggle_collapse(self) -> None:
        self._set_collapsed(not self._target_collapsed)

    def _apply_running_lock(self) -> None:
        locked = self._running
        for btn in self._lock_buttons:
            btn.set_interactive(not locked)

    def _on_play_clicked(self) -> None:
        self._hide_tip()
        if self._running:
            self._stop_running()
            return
        if self.monitor_region is None:
            self._prompt_select_region()
            return
        self._begin_running()

    def _prompt_select_region(self) -> None:
        self._tip_timer.stop()
        self._tip_btn = None
        anchor = QRect(self.btn_play.mapToGlobal(QPoint(0, 0)), self.btn_play.size())
        self._tip.popup("请先框选监视区域", anchor)
        self._hint_timer.start()

    def _begin_running(self) -> None:
        if self.monitor_region is None:
            return
        if not weights_ready():
            print(f"Missing YOLO weights: {WEIGHTS_FILE}")
            print("Place yolo26l.pt in the Download folder next to the program.")
            return
        self._running = True
        self._alerting = False
        self._shot_cool = False
        self._shot_kinds = frozenset()
        self._alert.reset()
        self._voice.stop()
        self.btn_play.set_toggled(True)
        self._apply_running_lock()
        self._set_collapsed(True)
        self._settings_panel.hide()
        self._overlay.set_alerting(False)
        self._overlay.set_region(self.monitor_region)
        self._overlay.clear_scene()
        self._overlay.show()
        self.raise_()
        if not self._runtime.start(self.monitor_region):
            self._stop_running()
            return

    def _stop_running(self) -> None:
        self._running = False
        self._alerting = False
        self._shot_cool = False
        self._shot_kinds = frozenset()
        self._cooldown.stop()
        self._voice.stop()
        self._alert.reset()
        self.btn_play.set_toggled(False)
        self._apply_running_lock()
        self._overlay.set_alerting(False)
        self._overlay.clear_scene()
        self._overlay.hide()
        self._runtime.pause()
        self._set_collapsed(False)

    def _on_settings_clicked(self) -> None:
        if self._running:
            return
        self._hide_tip()
        geo = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        self._settings_panel.popup_above(geo)

    def _apply_capture_affinity(self) -> None:
        apply_capture_affinity(self)
        apply_capture_affinity(self._overlay)
        apply_capture_affinity(self._settings_panel)
        apply_capture_affinity(self._list_panel)
        apply_capture_affinity(self._tip)
        apply_capture_affinity(self._exit_popup)
        about = getattr(self._exit_popup, "_about", None)
        if about is not None:
            apply_capture_affinity(about)
        if self._picker is not None:
            apply_capture_affinity(self._picker)

    def _on_settings_changed(self, settings) -> None:
        set_demo_capture(bool(settings.demo_record))
        self._overlay.apply_settings(settings)
        self._apply_capture_affinity()
        if self._running:
            self._runtime.apply_settings(settings)

    def _on_scene_ready(self, parking, intrusion, image_size, settings) -> None:
        if not self._running or self.monitor_region is None:
            return
        self._overlay.set_region(self.monitor_region)
        if not self._overlay.isVisible():
            self._overlay.show()
        self.raise_()
        alert = self._alert.evaluate(parking, intrusion, settings)
        self._alerting = alert.active
        self._overlay.set_alerting(self._alerting)
        self._overlay.set_scene(
            parking,
            intrusion,
            image_size,
            settings,
            alert.items if alert.active else None,
        )
        if self._alerting:
            if self._should_save_shot(alert.kinds):
                self._save_alert_shot(alert, image_size, settings)
            self._voice.update(alert.voice_kind if settings.voice_alert else None)
            if settings.auto_open_list:
                kind = alert.voice_kind
                QTimer.singleShot(0, lambda k=kind: self._open_alert_list(notice_kind=k))
            return
        self._voice.update(None)

    def _should_save_shot(self, kinds: frozenset[str]) -> bool:
        if not kinds:
            return False
        if not self._shot_cool:
            return True
        return kinds > self._shot_kinds

    def _save_alert_shot(self, alert: Alert, image_size, settings) -> None:
        if self.monitor_region is None:
            return
        with capture_hidden(self._overlay, self):
            path = save_alert_image(
                self.monitor_region,
                alert.items,
                alert.prefix,
                image_size,
                settings,
            )
        if path is not None:
            send_alert_async(settings, path, alert.kind_label)
        self._shot_cool = True
        self._shot_kinds = alert.kinds
        self._cooldown.start(int(settings.cooldown_sec) * 1000)

    def _on_cooldown_end(self) -> None:
        self._shot_cool = False
        self._shot_kinds = frozenset()

    def _shutdown(self) -> None:
        if getattr(self, "_did_shutdown", False):
            return
        self._did_shutdown = True
        self._cooldown.stop()
        self._voice.stop()
        self._runtime.shutdown()
        self._overlay.hide()
        self._overlay.close()
        self._list_panel.hide()
        self._list_panel.close()

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)

    def _on_select_clicked(self) -> None:
        if self._running or self._picker is not None:
            return
        self._hide_tip()
        self._list_panel.hide()
        self._overlay.hide()
        self.btn_select.set_toggled(True)
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
        self.hide()
        QTimer.singleShot(120, self._open_picker)

    def _open_picker(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        virt = virtual_desktop()
        if virt.isEmpty():
            self._end_pick()
            return
        picker = RegionPicker(virt)
        picker.selected.connect(self._on_region_selected)
        picker.cancelled.connect(self._on_region_cancelled)
        self._picker = picker
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _on_region_selected(self, rect: QRect) -> None:
        self.monitor_region = QRect(rect)
        self._end_pick()

    def _on_region_cancelled(self) -> None:
        self._end_pick()

    def _end_pick(self) -> None:
        self.btn_select.set_toggled(False)
        self._picker = None
        self.show()
        self.raise_()
        self.activateWindow()
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)

    def _on_list_clicked(self) -> None:
        self._open_alert_list()

    def _open_alert_list(self, notice_kind: str | None = None) -> None:
        if not self.isVisible() and self._picker is not None:
            return
        self._hide_tip()
        self._settings_panel.hide()
        self._list_was_running = bool(self._running)
        if self._running:
            self._stop_running()
        self._list_panel.show_at(self._capsule_global())
        if notice_kind:
            self._voice.loop_until_move(notice_kind)
        self.raise_()
        self.activateWindow()

    def _on_list_closed(self, resume: bool) -> None:
        self._voice.stop()
        self.raise_()
        self.activateWindow()
        if (
            resume
            and self._list_was_running
            and self.monitor_region is not None
            and not self._running
        ):
            self._begin_running()
        self._list_was_running = False

    def _on_btn_hover(self, btn: MetalButton) -> None:
        self._tip_btn = btn
        self._tip.hide()
        self._tip_timer.start()

    def _on_btn_leave(self) -> None:
        self._tip_timer.stop()
        self._tip_btn = None
        self._tip.hide()

    def _show_tip(self) -> None:
        btn = self._tip_btn
        if btn is None or not btn.isVisible() or btn._face_opacity < 0.45:
            return
        text = TIPS.get(btn.kind, "")
        if not text:
            return
        top_left = btn.mapToGlobal(QPoint(0, 0))
        self._tip.popup(text, QRect(top_left, btn.size()))

    def _hide_tip(self) -> None:
        self._tip_timer.stop()
        self._hint_timer.stop()
        self._tip_btn = None
        self._tip.hide()

    def _capsule_global(self) -> QRect:
        return QRect(
            self.mapToGlobal(QPoint(self._body_offset(), 0)),
            QSize(self._body_width(), self.height()),
        )

    def show_exit_popup(self, global_pos: QPoint) -> None:
        self._hide_tip()
        self._exit_popup.popup_at(global_pos, self._capsule_global())

    def contextMenuEvent(self, event) -> None:
        pos = event.pos()
        if pos.x() >= self._body_offset():
            self.show_exit_popup(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def _layout_buttons(self) -> None:
        y = T.SHADOW + T.PAD
        left = self._body_offset() + T.SHADOW + T.PAD
        right = self.width() - T.SHADOW - T.PAD - T.BTN_SIZE

        self.btn_play.move(left, y)
        self.btn_collapse.move(right, y)

        # Keep middle buttons anchored to the right so they stay put
        # while the window's left edge retracts. The list button slides
        # one slot right to take the fading settings button's place.
        self.btn_settings.move(right - T.STEP, y)
        self.btn_list.move(round(right - T.STEP * (2.0 - self._t)), y)
        self.btn_select.move(right - T.STEP * 3, y)

    def start_window_drag(self, global_pos: QPoint) -> None:
        self._hide_tip()
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def drag_window_to(self, global_pos: QPoint) -> None:
        if self._drag_offset is None:
            return
        if self._anim.state() == QPropertyAnimation.State.Running:
            return
        self.move(global_pos - self._drag_offset)

    def end_window_drag(self) -> None:
        self._drag_offset = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.x() >= self._body_offset():
                self.start_window_drag(event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.drag_window_to(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.end_window_drag()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body = QRectF(
            T.SHADOW + self._body_offset(),
            T.SHADOW,
            self._body_width() - T.SHADOW * 2,
            self.height() - T.SHADOW * 2,
        )
        radius = body.height() / 2.0

        # Soft stacked shadow
        for i in range(8, 0, -1):
            extra = i * 0.7
            s = body.adjusted(-extra * 0.45, -extra * 0.15, extra * 0.45, extra * 0.95)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 7 + i))
            p.drawRoundedRect(s, radius + extra * 0.25, radius + extra * 0.25)

        clip = QPainterPath()
        clip.addRoundedRect(body, radius, radius)

        metal = QLinearGradient(body.topLeft(), body.bottomLeft())
        metal.setColorAt(0.00, T.WINDOW_TOP)
        metal.setColorAt(0.18, QColor(44, 47, 53))
        metal.setColorAt(0.50, T.WINDOW_MID)
        metal.setColorAt(0.82, QColor(20, 22, 25))
        metal.setColorAt(1.00, T.WINDOW_BOT)
        p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(metal)
        p.drawRoundedRect(body, radius, radius)

        # Brushed metal bands
        p.setOpacity(0.07)
        band = QLinearGradient(body.topLeft(), body.topRight())
        band.setColorAt(0.0, QColor(0, 0, 0, 0))
        band.setColorAt(0.35, QColor(255, 255, 255, 80))
        band.setColorAt(0.7, QColor(0, 0, 0, 40))
        band.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(band)
        p.drawRoundedRect(body, radius, radius)
        p.setOpacity(1.0)

        # Top glass sheen
        sheen = QLinearGradient(body.x(), body.y(), body.x(), body.y() + body.height() * 0.55)
        sheen.setColorAt(0.0, T.WINDOW_SHEEN)
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        p.drawRoundedRect(
            QRectF(body.x(), body.y(), body.width(), body.height() * 0.55),
            radius,
            radius,
        )

        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(T.WINDOW_RIM, 1.15))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        # Inner bottom edge
        inner_pen = QPen(QColor(0, 0, 0, 90), 1.0)
        p.setPen(inner_pen)
        p.drawRoundedRect(body.adjusted(1.2, 1.2, -1.2, -1.2), radius - 1, radius - 1)
