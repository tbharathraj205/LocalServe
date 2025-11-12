#!/usr/bin/env python3
import sys
import signal
from PyQt6.QtWidgets import QApplication
from gui import HttpServerGUI


def main():
    app = QApplication(sys.argv)
    win = HttpServerGUI()
    win.show()

    def cleanup(*_):
        win._exit_app()

    signal.signal(signal.SIGINT, cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
