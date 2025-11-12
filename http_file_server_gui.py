#!/usr/bin/env python3
"""
http_file_server_gui.py

A PyQt6/PyQt5 desktop app to run Python’s built-in http.server with a clean UI.

Features:
- Folder selection (browse)
- Auto-detect free port (manual override allowed)
- Dark/Light theme toggle
- Start/Stop server (subprocess)
- Displays server status + URL
- Auto-copies URL to clipboard
- QR code for local access
- Live log viewer (stdout/stderr)
- System tray minimize (Show/Hide/Stop/Exit)
"""

import sys
import os
import socket
import subprocess
import threading
import queue
import signal
import time
from pathlib import Path
from io import BytesIO

# --- Handle PyQt6 / PyQt5 compatibility ---
try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
        QFileDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox,
        QSpinBox, QMessageBox, QSystemTrayIcon, QMenu, QStyle
    )
    from PyQt6.QtGui import QPixmap, QImage, QIcon, QAction
    from PyQt6.QtCore import Qt, QTimer, QSize
    PYQT_VERSION = 6
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
        QFileDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox,
        QSpinBox, QMessageBox, QSystemTrayIcon, QMenu, QAction, QStyle
    )
    from PyQt5.QtGui import QPixmap, QImage, QIcon
    from PyQt5.QtCore import Qt, QTimer, QSize
    PYQT_VERSION = 5

import qrcode
from PIL import Image
import pyperclip


# ------------------ Utility functions ------------------

def find_local_ip():
    """Return the local IP address (not 127.0.0.1)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip
    except Exception:
        return "127.0.0.1"


def is_port_free(port, host="0.0.0.0"):
    """Check if a port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(start=8000, host="0.0.0.0"):
    """Find the next available port from start upwards."""
    for port in range(start, 9000):
        if is_port_free(port, host):
            return port
    raise RuntimeError("No free ports found in range 8000-9000.")


def generate_qr_pixmap(url: str, size: int = 240) -> QPixmap:
    """Generate QR code QPixmap for a given URL."""
    qr = qrcode.QRCode(
        version=1, box_size=6, border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_L
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    qimg = QImage.fromData(buf.getvalue())
    return QPixmap.fromImage(qimg)


# ------------------ Logger Thread ------------------

class ProcessLogger(threading.Thread):
    """Reads process stdout/stderr and pushes to a queue."""
    def __init__(self, process, q):
        super().__init__(daemon=True)
        self.process = process
        self.q = q
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            if self.process.poll() is not None:
                break
            line = self.process.stdout.readline()
            if line:
                self.q.put(("OUT", line.strip()))
            err = self.process.stderr.readline()
            if err:
                self.q.put(("ERR", err.strip()))
        # Drain remaining
        for line in self.process.stdout:
            self.q.put(("OUT", line.strip()))
        for line in self.process.stderr:
            self.q.put(("ERR", line.strip()))

    def stop(self):
        self._stop.set()


# ------------------ Main GUI ------------------

class HttpServerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple HTTP File Server")
        self.setMinimumSize(850, 600)

        self.process = None
        self.logger_thread = None
        self.log_queue = queue.Queue()
        self.server_running = False
        self._exiting = False

        self._build_ui()
        self._create_tray_icon()

        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self._drain_log_queue)
        self.log_timer.start(100)

        self._apply_light_theme()

    # ----------- UI -----------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Folder and port controls
        top_group = QGroupBox("Server Controls")
        tg_layout = QGridLayout()

        tg_layout.addWidget(QLabel("Folder to Serve:"), 0, 0)
        self.folder_line = QLineEdit(str(Path.home()))
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_folder)
        tg_layout.addWidget(self.folder_line, 0, 1)
        tg_layout.addWidget(browse_btn, 0, 2)

        tg_layout.addWidget(QLabel("Port:"), 1, 0)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(find_free_port(8000))
        auto_btn = QPushButton("Auto-detect")
        auto_btn.clicked.connect(self._auto_detect_port)
        tg_layout.addWidget(self.port_spin, 1, 1)
        tg_layout.addWidget(auto_btn, 1, 2)

        self.start_btn = QPushButton("Start Server")
        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_server)
        self.stop_btn.clicked.connect(self._stop_server)

        self.theme_btn = QPushButton("Switch to Dark")
        self.theme_btn.setCheckable(True)
        self.theme_btn.clicked.connect(self._toggle_theme)

        tg_layout.addWidget(self.start_btn, 2, 1)
        tg_layout.addWidget(self.stop_btn, 2, 2)
        tg_layout.addWidget(self.theme_btn, 3, 2)

        top_group.setLayout(tg_layout)
        layout.addWidget(top_group)

        # Access info
        mid_group = QGroupBox("Access Info")
        mg_layout = QHBoxLayout()

        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("Server URL:"))
        self.url_display = QLineEdit()
        self.url_display.setReadOnly(True)
        left_box.addWidget(self.url_display)
        self.copy_note = QLabel("")
        left_box.addWidget(self.copy_note)
        mg_layout.addLayout(left_box)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(260, 260)
        mg_layout.addWidget(self.qr_label)
        mid_group.setLayout(mg_layout)
        layout.addWidget(mid_group)

        # Log viewer
        log_group = QGroupBox("Server Log")
        lg_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        lg_layout.addWidget(self.log_text)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_text.clear)
        lg_layout.addWidget(clear_btn)
        log_group.setLayout(lg_layout)
        layout.addWidget(log_group, 1)

        self.status_label = QLabel("Status: Stopped")
        layout.addWidget(self.status_label)

    # ----------- Behavior -----------

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_line.setText(folder)

    def _auto_detect_port(self):
        self.port_spin.setValue(find_free_port(8000))

    def _toggle_theme(self):
        if self.theme_btn.isChecked():
            self._apply_dark_theme()
            self.theme_btn.setText("Switch to Light")
        else:
            self._apply_light_theme()
            self.theme_btn.setText("Switch to Dark")

    def _apply_dark_theme(self):
        self.setStyleSheet("""
        QWidget { background-color: #121212; color: #e0e0e0; }
        QPushButton { background-color: #333; color: #fff; border: 1px solid #555; border-radius:5px; padding:5px;}
        QLineEdit, QTextEdit { background-color: #1e1e1e; color: #ddd; border: 1px solid #555;}
        QGroupBox { border: 1px solid #555; margin-top:6px; padding:6px; }
        """)

    def _apply_light_theme(self):
        self.setStyleSheet("""
        QWidget { background-color: #f8f9fb; color: #111; }
        QPushButton { background-color: #fff; border: 1px solid #ccc; border-radius:5px; padding:5px;}
        QLineEdit, QTextEdit { background-color: #fff; color: #111; border: 1px solid #ccc;}
        QGroupBox { border: 1px solid #ccc; margin-top:6px; padding:6px; }
        """)

    def _start_server(self):
        if self.server_running:
            return

        folder = self.folder_line.text()
        port = self.port_spin.value()

        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Error", "Invalid folder path.")
            return

        if not is_port_free(port):
            port = find_free_port(8000)
            self.port_spin.setValue(port)

        cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"]

        try:
            self.process = subprocess.Popen(
                cmd, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))
            return

        self.server_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Status: Running on port {port}")

        local_ip = find_local_ip()
        url = f"http://{local_ip}:{port}/"
        self.url_display.setText(url)
        pyperclip.copy(url)
        self.copy_note.setText("URL copied to clipboard")

        self.qr_label.setPixmap(generate_qr_pixmap(url))

        self.logger_thread = ProcessLogger(self.process, self.log_queue)
        self.logger_thread.start()
        self.log_text.append(f"[SYS] Server started at {url}")

    def _stop_server(self):
        if not self.server_running:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except Exception:
            self.process.kill()
        self.server_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.log_text.append("[SYS] Server stopped.")

    def _drain_log_queue(self):
        while not self.log_queue.empty():
            typ, line = self.log_queue.get()
            prefix = f"[{typ}]"
            self.log_text.append(f"{prefix} {line}")

        if self.server_running and self.process.poll() is not None:
            self._stop_server()

    # ----------- Tray icon -----------

    def _create_tray_icon(self):
        self.tray = QSystemTrayIcon(self)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)

        menu = QMenu()
        show_action = QAction("Show/Hide Window")
        stop_action = QAction("Stop Server")
        exit_action = QAction("Exit App")

        show_action.triggered.connect(self._toggle_window)
        stop_action.triggered.connect(self._stop_server)
        exit_action.triggered.connect(self._exit_app)

        menu.addAction(show_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

        QApplication.setQuitOnLastWindowClosed(False)

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event):
        if self._exiting:
            event.accept()
        else:
            event.ignore()
            self.hide()
            self.tray.showMessage("Simple HTTP Server", "App minimized to tray.", QSystemTrayIcon.MessageIcon.Information, 3000)

    def _exit_app(self):
        self._exiting = True
        if self.server_running:
            self._stop_server()
        QApplication.quit()


# ------------------ Main ------------------

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
