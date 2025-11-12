#!/usr/bin/env python3
"""
http_file_server_gui.py

A PyQt6 desktop application that provides a GUI for running Python's built-in http.server.

Features:
- Folder selection (browse)
- Auto-detect free port starting at 8000 (manual override allowed)
- Dark / Light theme toggle
- Start / Stop server (subprocess.Popen)
- Shows server status, URL, auto-copies URL to clipboard
- Generates QR code for mobile access (local IP)
- Live log viewer (stdout/stderr) with auto-scroll and clear
- Run minimized to system tray with tray menu (Show/Hide, Stop Server, Exit)
- Clean exception handling and graceful shutdown

Dependencies:
    pip install PyQt6 qrcode pillow pyperclip

Author: tbharathraj205
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

# GUI imports
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox,
    QSpinBox, QMessageBox, QSystemTrayIcon, QMenu, QAction, QStyle
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QCloseEvent
from PyQt6.QtCore import Qt, QTimer, QSize

# Other libs
import qrcode
from PIL import Image
import pyperclip

# ---------- Utility functions ----------

def find_local_ip():
    """Return local IP address (non-loopback). Uses UDP socket trick."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # doesn't need to succeed, just choose an address that routes externally
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip
    except Exception:
        return "127.0.0.1"


def is_port_free(port, host="0.0.0.0"):
    """Check if a port is free on the given host (bind attempt)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(start=8000, host="0.0.0.0", max_search=1000):
    """Find a free port starting from `start` upwards. Returns port int or raises RuntimeError."""
    for p in range(start, start + max_search):
        if is_port_free(p, host):
            return p
    raise RuntimeError(f"No free port found starting at {start}")


def generate_qr_pixmap(url: str, size: int = 240) -> QPixmap:
    """Generate a QR code QPixmap from a URL using qrcode + PIL then convert to QPixmap."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    qimg = QImage.fromData(buf.getvalue())
    return QPixmap.fromImage(qimg)


# ---------- Worker / reader thread for subprocess output ----------

class ProcessLogger(threading.Thread):
    """
    Reads process stdout and stderr lines and pushes them into a queue for the GUI to consume.
    Uses non-blocking line reading with iteration because Popen streams are text-mode.
    """

    def __init__(self, process: subprocess.Popen, out_queue: queue.Queue):
        super().__init__(daemon=True)
        self.process = process
        self.out_queue = out_queue
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        # Read both stdout and stderr lines
        # We'll poll process.stdout and process.stderr separately
        try:
            # It's simpler and reliable to read from both using their file descriptors
            # but we'll loop while process is alive and try reading lines with timeout.
            while not self._stop_event.is_set():
                if self.process.stdout:
                    line = self.process.stdout.readline()
                    if line:
                        self.out_queue.put(("OUT", line.rstrip("\n")))
                if self.process.stderr:
                    err = self.process.stderr.readline()
                    if err:
                        self.out_queue.put(("ERR", err.rstrip("\n")))
                # break loop if process finished and no more data
                if self.process.poll() is not None:
                    # drain remaining
                    if self.process.stdout:
                        for line in self.process.stdout:
                            self.out_queue.put(("OUT", line.rstrip("\n")))
                    if self.process.stderr:
                        for line in self.process.stderr:
                            self.out_queue.put(("ERR", line.rstrip("\n")))
                    break
                # be gentle on CPU
                time.sleep(0.05)
        except Exception as e:
            self.out_queue.put(("SYS", f"Logger thread exception: {e}"))


# ---------- Main Application Window ----------

class HttpServerGUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Simple HTTP File Server")
        self.setMinimumSize(840, 600)

        # State
        self.process = None  # subprocess.Popen instance
        self.logger_thread = None  # ProcessLogger
        self.log_queue = queue.Queue()
        self.server_running = False

        # Default serve folder (user's home)
        self.serve_folder = str(Path.home())
        self.start_port = 8000

        # UI elements
        self._build_ui()

        # Tray
        self._create_tray_icon()

        # Timer to poll log queue
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(100)  # ms
        self.log_timer.timeout.connect(self._drain_log_queue)
        self.log_timer.start()

        # On close flag
        self._exiting = False

        # Apply default theme (light)
        self._apply_light_theme()

    # ---------- UI Construction ----------

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Top group: folder, port, start/stop
        top_group = QGroupBox("Server controls")
        tg_layout = QGridLayout()
        tg_layout.setColumnStretch(1, 1)
        tg_layout.setHorizontalSpacing(8)
        tg_layout.setVerticalSpacing(8)

        # Folder selector
        folder_label = QLabel("Folder to serve:")
        self.folder_line = QLineEdit(self.serve_folder)
        self.folder_line.setPlaceholderText("Select folder to serve")
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._browse_folder)

        tg_layout.addWidget(folder_label, 0, 0)
        tg_layout.addWidget(self.folder_line, 0, 1)
        tg_layout.addWidget(self.browse_btn, 0, 2)

        # Port
        port_label = QLabel("Port:")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        # Find free port to pre-fill
        try:
            free_p = find_free_port(self.start_port)
        except Exception:
            free_p = self.start_port
        self.port_spin.setValue(free_p)
        self.auto_detect_btn = QPushButton("Auto-detect")
        self.auto_detect_btn.clicked.connect(self._auto_detect_port)

        tg_layout.addWidget(port_label, 1, 0)
        tg_layout.addWidget(self.port_spin, 1, 1)
        tg_layout.addWidget(self.auto_detect_btn, 1, 2)

        # Start / Stop buttons
        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self._start_server)
        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self._stop_server)
        self.stop_btn.setEnabled(False)

        btn_hbox = QHBoxLayout()
        btn_hbox.setSpacing(8)
        btn_hbox.addWidget(self.start_btn)
        btn_hbox.addWidget(self.stop_btn)

        tg_layout.addLayout(btn_hbox, 2, 1)

        # Theme toggle
        self.theme_btn = QPushButton("Switch to Dark")
        self.theme_btn.setCheckable(True)
        self.theme_btn.clicked.connect(self._toggle_theme)
        tg_layout.addWidget(self.theme_btn, 2, 2)

        top_group.setLayout(tg_layout)
        layout.addWidget(top_group)

        # Middle group: URL display + QR + copy button
        mid_group = QGroupBox("Access information")
        mg_layout = QHBoxLayout()
        mg_layout.setSpacing(12)

        left_v = QVBoxLayout()
        lbl = QLabel("Server URL:")
        self.url_display = QLineEdit()
        self.url_display.setReadOnly(True)
        left_v.addWidget(lbl)
        left_v.addWidget(self.url_display)

        # Auto copy note
        self.copy_note = QLabel("")
        left_v.addWidget(self.copy_note)

        mg_layout.addLayout(left_v, 2)

        # QR code display
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(260, 260)
        self.qr_label.setStyleSheet("border: 1px solid rgba(0,0,0,0.08);")
        mg_layout.addWidget(self.qr_label, 1, Qt.AlignmentFlag.AlignCenter)

        mid_group.setLayout(mg_layout)
        layout.addWidget(mid_group)

        # Log viewer
        log_group = QGroupBox("Server log")
        lg_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setAcceptRichText(False)
        lg_layout.addWidget(self.log_text)

        log_btn_h = QHBoxLayout()
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.log_text.clear)
        self.autoscroll_cb = QPushButton("Auto-Scroll: ON")
        self.autoscroll_cb.setCheckable(True)
        self.autoscroll_cb.setChecked(True)
        self.autoscroll_cb.clicked.connect(self._toggle_autoscroll)
        log_btn_h.addWidget(self.clear_log_btn)
        log_btn_h.addWidget(self.autoscroll_cb)
        lg_layout.addLayout(log_btn_h)

        log_group.setLayout(lg_layout)
        layout.addWidget(log_group, stretch=1)

        # Status bar
        status_h = QHBoxLayout()
        self.status_label = QLabel("Status: Stopped")
        status_h.addWidget(self.status_label)
        status_h.addStretch()
        layout.addLayout(status_h)

        self.setLayout(layout)

    # ---------- Slots / Behavior ----------

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to serve", self.folder_line.text())
        if folder:
            self.folder_line.setText(folder)

    def _auto_detect_port(self):
        try:
            p = find_free_port(self.start_port)
            self.port_spin.setValue(p)
            QMessageBox.information(self, "Port detected", f"Found free port: {p}")
        except Exception as e:
            QMessageBox.warning(self, "Port detect error", str(e))

    def _toggle_theme(self, checked):
        if checked:
            self._apply_dark_theme()
            self.theme_btn.setText("Switch to Light")
        else:
            self._apply_light_theme()
            self.theme_btn.setText("Switch to Dark")

    def _apply_dark_theme(self):
        # Very basic dark theme - feel free to expand / tweak
        dark_style = """
            QWidget { background-color: #121212; color: #e0e0e0; }
            QLineEdit, QTextEdit { background-color: #1e1e1e; color: #e0e0e0; border: 1px solid #2e2e2e; }
            QPushButton { background-color: #2a2a2a; border: 1px solid #3a3a3a; padding: 6px; border-radius:6px; }
            QPushButton:checked { background-color: #0078d7; color: white; }
            QGroupBox { border: 1px solid #2e2e2e; margin-top: 6px; padding: 8px; }
        """
        self.setStyleSheet(dark_style)

    def _apply_light_theme(self):
        light_style = """
            QWidget { background-color: #f7f8fa; color: #111111; }
            QLineEdit, QTextEdit { background-color: #ffffff; color: #111111; border: 1px solid #e1e1e6; }
            QPushButton { background-color: #ffffff; border: 1px solid #d0d0d5; padding: 6px; border-radius:6px; }
            QPushButton:checked { background-color: #0078d7; color: white; }
            QGroupBox { border: 1px solid #e1e1e6; margin-top: 6px; padding: 8px; }
        """
        self.setStyleSheet(light_style)

    def _toggle_autoscroll(self):
        if self.autoscroll_cb.isChecked():
            self.autoscroll_cb.setText("Auto-Scroll: ON")
        else:
            self.autoscroll_cb.setText("Auto-Scroll: OFF")

    def _start_server(self):
        if self.server_running:
            return

        folder = self.folder_line.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Invalid folder", "Please select a valid folder to serve.")
            return

        port = int(self.port_spin.value())

        # Ensure chosen port is free (warn if not)
        if not is_port_free(port):
            reply = QMessageBox.question(
                self, "Port in use",
                f"Port {port} appears to be in use. Try another port?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    port = find_free_port(self.start_port)
                    self.port_spin.setValue(port)
                except Exception as e:
                    QMessageBox.critical(self, "No port", str(e))
                    return
            else:
                return

        # Build command
        # Use explicit sys.executable to ensure the same Python interpreter is used
        cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"]

        try:
            # Start subprocess with pipes to capture logs. Use universal_newlines/text.
            self.process = subprocess.Popen(
                cmd,
                cwd=folder,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        except Exception as e:
            QMessageBox.critical(self, "Failed to start server", f"Could not start server:\n{e}")
            self.process = None
            return

        self.server_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Status: Running on port {port}")

        # Compute local URL
        local_ip = find_local_ip()
        url = f"http://{local_ip}:{port}/"
        self.url_display.setText(url)

        # Copy to clipboard (pyperclip)
        try:
            pyperclip.copy(url)
            # Also set small note
            self.copy_note.setText("URL copied to clipboard.")
        except Exception:
            # Fallback to Qt clipboard if pyperclip fails
            try:
                QApplication.clipboard().setText(url)
                self.copy_note.setText("URL copied to clipboard (Qt).")
            except Exception:
                self.copy_note.setText("Could not copy to clipboard.")

        # Generate QR
        try:
            pix = generate_qr_pixmap(url, size=260)
            self.qr_label.setPixmap(pix.scaled(self.qr_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            self.log_text.append(f"[SYS] QR generation failed: {e}")

        # Start logger thread to read stdout/stderr
        self.log_text.append(f"[SYS] Server started with PID {self.process.pid}\n")
        self.log_timer.start()
        self.logger_thread = ProcessLogger(self.process, self.log_queue)
        self.logger_thread.start()

    def _stop_server(self):
        if not self.server_running:
            return

        # Terminate subprocess gracefully
        try:
            if self.process and self.process.poll() is None:
                # Try terminate nicely
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.log_text.append("[SYS] Server process stopped.\n")
        except Exception as e:
            self.log_text.append(f"[SYS] Error stopping server: {e}\n")

        # Signal logger thread to stop
        try:
            if self.logger_thread:
                self.logger_thread.stop()
                self.logger_thread.join(timeout=1)
        except Exception:
            pass

        self.process = None
        self.logger_thread = None
        self.server_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.copy_note.setText("")
        self.url_display.clear()
        self.qr_label.clear()

    def _drain_log_queue(self):
        """Called on timer to pull log lines from logger thread into QTextEdit."""
        drained = False
        while not self.log_queue.empty():
            drained = True
            try:
                typ, line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if typ == "OUT":
                self.log_text.append(f"[OUT] {line}")
            elif typ == "ERR":
                self.log_text.append(f"[ERR] {line}")
            else:
                self.log_text.append(f"[{typ}] {line}")
        # Auto-scroll if enabled
        if drained and self.autoscroll_cb.isChecked():
            self.log_text.moveCursor(self.log_text.textCursor().End)

        # If process ended, update status
        if self.server_running and self.process:
            if self.process.poll() is not None:
                # collect exit code
                rc = self.process.returncode
                self.log_text.append(f"[SYS] Server exited with code {rc}")
                # stop server state
                self._stop_server()

    # ---------- System tray ----------

    def _create_tray_icon(self):
        # Create tray icon and menu
        self.tray = QSystemTrayIcon(self)
        # Use a standard icon (computer) if no custom icon available
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)

        menu = QMenu()

        self.action_show = QAction("Show/Hide Window")
        self.action_show.triggered.connect(self._toggle_window_visible)
        menu.addAction(self.action_show)

        self.action_stop = QAction("Stop Server")
        self.action_stop.triggered.connect(self._stop_server)
        menu.addAction(self.action_stop)

        menu.addSeparator()

        self.action_exit = QAction("Exit App")
        self.action_exit.triggered.connect(self._exit_app)
        menu.addAction(self.action_exit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        # Ensure app doesn't quit when window closed
        QApplication.setQuitOnLastWindowClosed(False)

    def _toggle_window_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def _tray_activated(self, reason):
        # For double click, toggle window
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window_visible()

    def _exit_app(self):
        # Clean stop server then quit
        self._exiting = True
        try:
            if self.server_running:
                self._stop_server()
        finally:
            QApplication.quit()

    # ---------- Close event handling (minimize to tray) ----------

    def closeEvent(self, event: QCloseEvent):
        # Instead of closing, minimize to tray (unless exiting)
        if self._exiting:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage("Simple HTTP File Server", "Application minimized to tray. Use tray menu to exit.", QSystemTrayIcon.MessageIcon.Information, 3000)

    # ---------- Clean up signals ----------

    def signal_cleanup(self):
        # Called on program exit to ensure subprocess is cleaned up
        try:
            if self.server_running:
                self._stop_server()
        except Exception:
            pass


# ---------- App Entrypoint ----------

def main():
    app = QApplication(sys.argv)
    window = HttpServerGUI()
    window.show()

    # Ensure clean shutdown on SIGINT (Ctrl+C in console)
    def handle_sigint(*args):
        window._exiting = True
        window.signal_cleanup()
        QApplication.quit()

    signal.signal(signal.SIGINT, lambda *args: handle_sigint())

    try:
        rc = app.exec()
        # On exit ensure server stopped
        window.signal_cleanup()
        sys.exit(rc)
    except Exception as e:
        print("Application error:", e)
        window.signal_cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
