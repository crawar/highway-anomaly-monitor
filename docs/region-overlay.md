# 监视区域框选、反馈与穿透边框

本文说明用户框选监视区域时的交互逻辑、选中后的视觉反馈，以及启动监测后如何用穿透窗口画出该区域边框。

相关代码：

| 职责 | 文件 |
| --- | --- |
| 点击「监视区域」、缓存坐标、启动后套 overlay | `app/window.py` |
| 全屏框选与选中闪烁 | `app/picker.py` |
| 穿透识别窗、区域边框与角标 | `app/overlay.py` |
| Win32 穿透 / 录屏亲和 | `app/win32util.py` |
| 尺寸、颜色、闪烁节拍 | `app/theme.py` |

---

## 1. 用户如何进入框选

主页「监视区域」按钮（虚线方框）接到点击后走 `_on_select_clicked`：

1. 监测中或已有框选窗时直接忽略。
2. 关掉提示、列表、识别 overlay，避免挡框选。
3. 选中按钮进入黄色闪烁（`set_toggled(True)`），表示正在选区域。
4. 主窗口先 `hide()`。为防止「最后一个窗没了程序退出」，临时 `setQuitOnLastWindowClosed(False)`。
5. 延迟 **120ms** 再打开框选窗，让主窗口先从屏幕上消失，避免框选时还看到 HUD。

未选区域就点启动时，不会自动进入框选，只在启动按钮旁提示「请先框选监视区域」。

---

## 2. 框选窗本身：不改桌面，只画橡皮筋

`RegionPicker` 铺满**虚拟桌面**（多屏拼成的并集，`virtual_desktop()`）。

它是无边框、置顶、透明的 Tool 窗，**不会截屏、不会压暗桌面**。桌面内容保持原样，用户只看到十字光标和黄色选择框。

为了让整块透明窗能收到鼠标（Windows layered 窗对全透明像素默认穿透），`paintEvent` 先铺一层 **alpha=1** 的黑底。肉眼看不见，但窗口可点。

框选阶段**不能穿透**：用户必须在这层上拖框。穿透只发生在后面的识别 overlay。

---

## 3. 拖框与提交

坐标都在框选窗客户区里（相对虚拟桌面左上角）：

1. 左键按下：记下起点，进入拖拽。
2. 移动：更新终点，每帧重绘 `QRect(起点, 终点).normalized()`。
3. 左键松开：宽、高都 ≥ `MIN_REGION`（8px）才提交，否则当作无效，框消失，可再拖。
4. 提交后进入「已选定」状态，不再改框，开始闪烁确认。

取消：

- 尚未提交时：Esc 或右键 → `cancelled`，不改已缓存区域。
- 已经提交、正在闪烁时：Esc / 右键 / 关窗都视为确认当前框，发出 `selected`。

提交后的矩形会 `translate(虚拟桌面左上角)`，变成**屏幕全局逻辑坐标**，再交给主窗。

---

## 4. 选中反馈

确认框是双层描边，不填充内部：

- 外圈：黄色 `PICK_BORDER`，约 2.4px
- 内圈：半透明白 `PICK_BORDER_INNER`，1px

闪烁：

- 周期 `PICK_BLINK_MS = 250`
- 共 `PICK_BLINK_TICKS = 8` 次翻转（亮/灭各 4 次）
- 总时长约 **2 秒**
- 灭的那半拍不画边框，看起来像黄框在闪

闪完（或闪的过程中取消键被当成确认）后关闭框选窗，发出 `selected(全局矩形)`。

主窗 `_on_region_selected`：

1. 把矩形存进 `HomeWindow.monitor_region`
2. `_end_pick()`：关掉按钮黄闪、清掉 picker 引用、重新显示主窗、恢复 `QuitOnLastWindowClosed`

此时**还不会**出现科技青监测边框。那条边框只在用户点启动、识别 overlay 显示之后才画。`monitor_region` 只是缓存，给检测截图和 overlay 几何用。

---

## 5. 启动后：穿透窗贴在选中区域上

`_begin_running()`：

1. `OverlayWindow.set_region(monitor_region)`：把 overlay **几何设成选中矩形**（窗口本身就是这块区域）。
2. `clear_scene()` 后 `show()`。
3. 检测进程按同一矩形截屏。

之后每次识别结果回来，`_on_scene_ready` 会再 `set_region` 一次，防止窗口被挪走。矩形宽高小于 2 则隐藏 overlay。

停止监测时 overlay 隐藏并清空场景，缓存的 `monitor_region` 仍保留，下次启动不用重选。

---

## 6. 穿透怎么做到

识别 overlay 必须让鼠标点到「后面的桌面 / 视频」，边框只是画上去。

**Qt 层**（`app/overlay.py`）：

- `WindowTransparentForInput`
- `WA_TransparentForMouseEvents`
- `WA_ShowWithoutActivating`（不抢焦点）
- 半透明背景、无边框、置顶 Tool 窗

**Win32 层**（`enable_click_through`，第一次 `showEvent` 调用）：

给 HWND 加上：

- `WS_EX_LAYERED`
- `WS_EX_TRANSPARENT`（命中测试穿透）
- `WS_EX_NOACTIVATE`
- `WS_EX_TOOLWINDOW`

同时 `DwmShowWindowAttribute` 关掉系统圆角，避免四角被切。

因此 overlay 上的虚线框、L 角、识别框都**看得见、点不着**。

框选窗故意不加这些标志，否则用户无法拖框。

---

## 7. 穿透之后，区域边框怎么画

overlay 客户区等于选中区域，边框画在 `self.rect()` 上，不必再映射一次全局坐标。

常态（监测中、无报警）：

- 颜色：科技青 `REGION_RUN = (0, 232, 214)`
- 线宽：`REGION_PEN = 5` 的虚线，`dash = [8, 6]`
- 矩形向内收半个线宽，避免笔画被裁切
- **不闪**

报警中：

- 颜色改红 `REGION_ALERT`
- `ALERT_BLINK_MS = 250` 翻转 `_region_on`
- 灭的半拍整圈边框（含角标）都不画，红虚线闪烁

四个 **L 型粗角**叠在虚线**最上面**，画在窗口外沿（`self.rect()`），用来盖住虚线在转角处的空档。角长 `REGION_CORNER_LEN = 22`，粗 `REGION_CORNER_PEN = 9`，过小的区域会跳过角标。

识别目标框是另外的 2px 实线（蓝/绿/红），和区域边框分开画。区域框先画目标、最后画边框，边框压在识别框之上。

---

## 8. 两阶段对照

```
用户点「监视区域」
        │
        ▼
  主窗隐藏 120ms
        │
        ▼
  RegionPicker 铺满虚拟桌面（可点击，不穿透）
        │
        ├─ 拖黄框 → 松开且足够大
        │         → 黄框闪约 2 秒
        │         → 缓存全局 QRect 到 monitor_region
        │
        └─ Esc / 右键（未提交）→ 取消，不改旧区域
        │
        ▼
  主窗回来，按钮恢复常态
        │
        ▼
  用户点启动（已有区域）
        │
        ▼
  OverlayWindow 几何 = monitor_region
  开启穿透 + 置顶
        │
        ├─ 无报警：科技青虚线 + L 角，常亮
        └─ 有报警：红虚线 + L 角，0.25s 闪一次
```

---

## 9. 和录屏的关系

overlay（以及 HUD）始终使用 `WDA_EXCLUDEFROMCAPTURE`，系统截图/部分录屏看不到边框，检测截屏也不会吃到自己画的框。

预警存图时会用 `capture_hidden` 临时把 overlay 排除出采集，保证 `Pic/` 里是干净画面，再按设置画报警框。默认只画红框；勾选「调试模式」后存图会画出全部识别框。

---

## 10. 改动时注意

- 框选窗不要加 `WS_EX_TRANSPARENT`，否则拖不到。
- overlay 必须保持穿透，否则会挡住下面的电影/桌面。
- 框选用虚拟桌面全局坐标；overlay 用「窗口 = 区域」局部绘制，两边不要混用。
- 选中闪烁（黄框、picker）和运行边框（青/红、overlay）是两套绘制，不要画在同一个窗上。
- 最小框 8px；overlay 还要求宽高 ≥ 2，过小会直接隐藏。
