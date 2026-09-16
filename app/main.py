from __future__ import annotations

import multiprocessing
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.window import HomeWindow
from app import VERSION


def main() -> None:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("CarFind")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")

    window = HomeWindow()
    screen = app.primaryScreen().availableGeometry()
    window.move(
        screen.center().x() - window.width() // 2,
        screen.center().y() - window.height() // 2,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
