# Highway Anomaly Monitor

高速公路异常监测（CarFind）。Windows 11 透明 HUD：框选监视区域后，用 YOLO 检测违停车辆与闯入目标，并支持语音、截图和钉钉推送。

**Author:** [crawar](https://github.com/crawar)

## YOLO26L 权重

本仓库**不包含**权重文件。请从 Ultralytics 官方发布页下载 **YOLO26 large（`yolo26l.pt`）**，放到项目目录 `Download/yolo26l.pt`。

官方下载链接：

https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt

Release 说明：https://github.com/ultralytics/assets/releases/tag/v8.4.0

## 运行前准备

1. Python 3.11+，在项目内创建虚拟环境（`.venv` 已加入忽略列表，需自行创建）。
2. 安装依赖：`pip install -r requirements.txt`，PyTorch 请按本机情况安装 CPU 或 CUDA 版本。
3. 复制 `config.example.json` 为 `config.json`，再按需填写钉钉等本地配置。`config.json` 不会进入 Git。
4. 将 `yolo26l.pt` 放入 `Download/`。
5. 双击 `run.bat`，或执行 `.venv\Scripts\python.exe -m app`。

打包：确认权重、示例配置和 `warning/*.wav` 齐全后运行 `build.bat`。打包产物在 `dist/`，不会提交到本仓库。

## 仓库里没有的内容

- `config.json`（避免泄露钉钉 Webhook / Client Secret）
- `Download/yolo26l.pt` 及 Ultralytics 本地缓存
- `dist/`、`build/` 打包结果
- `Pic/` 中的预警截图
- 测试视频
- 虚拟环境 `.venv`

## 许可与用途

面向高速公路监控场景的内部演示与业务工具。作者为 GitHub 用户 [crawar](https://github.com/crawar)。
