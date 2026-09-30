# Highway Anomaly Monitor

高速公路异常监测（CarFind **V1.2.1**）。Windows 11 透明 HUD：框选监视区域后，用 YOLO 检测违停车辆、拥堵与闯入目标，并支持语音、截图和钉钉推送。

**Author:** [crawar](https://github.com/crawar)

## V1.2.1

- **监测中锁定预警列表**：启动后主界面收起时，预警列表按钮与框选、设置一样不可点。
- **拥堵车辆数**：改为 20 到 50，每 5 辆一档，默认 20。
- **报警图**：保存的是 YOLO 实际检测的那一帧，不再在报警时重新截屏。

## V1.2.0

本版本增加拥堵报警，并把设置按报警类型分页。安装包不再附带 `config.json`。

- **拥堵**：连续 2 帧车辆数达到设定值才报警。同一帧只报一种，优先级为违停、拥堵、闯入。拥堵提示音为 `warning/Bwarning.wav`。
- **设置分页**：主要页保留监测间隔、车辆置信度、报警冷却和勾选框；违停、闯入、拥堵各自一页。
- **未设区域可启动**：未框选时点启动会提示将以主显示器全屏监测，5 秒后默认继续。
- **安装包**：`build.bat` 不再复制 `config.json`，避免钉钉密钥进入分发包。程序在首次保存设置时于 exe 旁生成该文件。

## V1.1.2

本版本主要完善预警后自动打开图片查看器，以及监测启动提示音。

- **就绪提示音**：任何一次启动监测都会先播放 `warning/Rwarning.wav`，播完后再开始实际检测。
- **无人值守关闭**：自动打开的图片查看器若 30 秒内未检测到鼠标移动，会停止报警音、关闭查看器，并立即恢复监测（等同点击关闭）。
- **立即恢复监测**：关闭自动弹出的查看器后不再等待 3 秒，立刻进入监测。

## V1.1.1

本版本主要增加预警后自动打开图片查看器，以及「视线引导」。

- **预警后自动打开图片**：监测中报警并生成截图后，自动弹出图片查看器；语音循环播放直到鼠标移动。从列表手动打开图片不会触发这段循环播报。关闭自动弹出的查看器约 3 秒后恢复监测。
- **视线引导**：打开查看器后，图中只有一个红框时，先正常显示 1 秒，再在 2 秒内渐进放大到 200%，并把红框尽量移到中央；多个红框时，1 秒后在各红框周围闪红圈。

## YOLO26L 权重

本仓库**不包含**权重文件。请从 Ultralytics 官方发布页下载 **YOLO26 large（`yolo26l.pt`）**，放到项目目录 `Download/yolo26l.pt`。

官方下载链接：

https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt

Release 说明：https://github.com/ultralytics/assets/releases/tag/v8.4.0

## 运行前准备

1. Python 3.11+，在项目内创建虚拟环境（`.venv` 已加入忽略列表，需自行创建）。
2. 安装依赖：`pip install -r requirements.txt`，PyTorch 请按本机情况安装 CPU 或 CUDA 版本。
3. 复制 `config.example.json` 为 `config.json`，再按需填写钉钉等本地配置。**`config.json` 含钉钉 Webhook / Client Secret，不会进入 Git，也不要提交到 GitHub。**
4. 将 `yolo26l.pt` 放入 `Download/`。
5. 双击 `run.bat`，或执行 `.venv\Scripts\python.exe -m app`。

打包：确认权重和 `warning/*.wav` 齐全后运行 `build.bat`。版本号取自 `app/__init__.py` 的 `VERSION`，产物目录为 `dist/CarFind-<版本号>/`（如 `dist/CarFind-V1.2.1/`），旧版本目录会保留；`dist/` 不会提交到本仓库。安装包不包含 `config.json`，以免带上钉钉密钥；首次在程序里保存设置时，会在 exe 旁边生成该文件。

## 主要设置（`config.json`）

- `interval_sec`：监测间隔，默认 2.5 秒。违停判定按帧数自适应。
- `parking_hold_sec`：违停时间，默认 10 秒。
- `parking_conf` / `intrusion_conf`：车辆置信度与闯入置信度，默认 0.50。
- `congestion_alert` / `congestion_count`：侦测拥堵，默认开启；拥堵车辆数默认 20，只取 20、25、30、35、40、45、50。
- `debug_mode`：调试模式。勾选后实时窗口和存图会显示全部识别框；关闭时实时窗口不画绿框，存图只保留红框。
- `auto_open_image`：预警后自动打开图片，默认勾选。勾选后报警会停监测、存图并弹出查看器；语音循环到鼠标移动才停。30 秒内鼠标未移动则关闭查看器并立即恢复监测；手动关闭同样立即恢复。
- `gaze_guidance`：视线引导。单红框会渐进放大居中；多红框会闪红圈。
- `cooldown_sec`：报警冷却。同样影响钉钉，仅在未启用 `auto_open_image` 时生效。
- `worker_threads`：检测进程的 torch 线程数，默认 4（1–16）。
- `worker_cpu_affinity`：把检测进程限定在指定逻辑 CPU 上，如 `"16-23"`，留空则不限制。
- 检测进程始终以「低于正常」优先级运行，让被监视的视频客户端优先拿到 CPU。

钉钉相关字段（`ding_webhook`、`ding_secret`、`ding_app_key`、`ding_app_secret`、`ding_keyword`）只应写在本机 `config.json`。仓库里的 `config.example.json` 只保留空字符串占位。

## 诊断日志

程序运行时会在程序目录下的 `logs/` 写入日志（不进入 Git），出现崩溃、卡死或整机重启时把整个 `logs/` 文件夹拷回来即可：

- `carfind-ui.log`：主界面进程。启动环境、显示器、启动/停止、报警、截图、每 60 秒一次心跳（两个进程的 CPU/内存/句柄），以及检测子进程意外退出的记录。
- `carfind-worker.log`：YOLO 检测子进程。模型加载耗时、每 60 秒一次的推理耗时汇总（`infer_avg`/`infer_max`/`over_interval`）与资源占用、异常和退出原因。
- `crash-*.log`：仅在进程发生原生崩溃（非 Python 异常）时写入调用栈。

每个文件 5 MB 自动滚动，最多保留 3 份历史。现场采集系统事件可用根目录 `collect_events.bat`（生成的报告同样不进入 Git）。

## 仓库里没有的内容

- `config.json`（避免泄露钉钉 Webhook / Client Secret）
- `Download/yolo26l.pt` 及 Ultralytics 本地缓存
- `dist/`、`build/` 打包结果
- `Pic/` 中的预警截图
- `logs/` 与 `collect_events.bat` 生成的诊断报告
- 测试视频
- 虚拟环境 `.venv`

## 许可与用途

面向高速公路监控场景的内部演示与业务工具。作者为 GitHub 用户 [crawar](https://github.com/crawar)。
