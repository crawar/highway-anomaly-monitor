from __future__ import annotations

import multiprocessing
import os
import sys

# The UI only touches numpy for alert snapshots; without this OpenBLAS spins up
# one thread per logical CPU on first import (measured: +23 threads, +750 MB
# committed). The detector process sets its own OMP_NUM_THREADS before torch.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app import VERSION, diag


def _qt_message(kind, context, message) -> None:
    log = diag.setup("ui")
    if kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        log.error("Qt: %s", message)
    elif kind == QtMsgType.QtWarningMsg:
        log.warning("Qt: %s", message)
    else:
        log.debug("Qt: %s", message)


def _log_screens(log, app: QApplication) -> None:
    for screen in app.screens():
        geo = screen.geometry()
        log.info(
            "screen %s geometry=%s dpr=%.2f primary=%s",
            screen.name(),
            (geo.x(), geo.y(), geo.width(), geo.height()),
            screen.devicePixelRatio(),
            screen is app.primaryScreen(),
        )


def main() -> None:
    log = diag.setup("ui")
    diag.install_excepthooks(log)
    diag.log_environment(log)
    qInstallMessageHandler(_qt_message)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("CarFind")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    from app.app_icon import create_app_icon

    app.setWindowIcon(create_app_icon())
    _log_screens(log, app)

    from app.window import HomeWindow

    window = HomeWindow()
    screen = app.primaryScreen().availableGeometry()
    window.move(
        screen.center().x() - window.width() // 2,
        screen.center().y() - window.height() // 2,
    )
    window.show()
    code = app.exec()
    log.info("===== UI process exiting normally code=%s =====", code)
    sys.exit(code)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
