Here’s a complete and clean **`README.md`** file for your project — ready to use on GitHub 👇

---


# 🚀 QuickShare Server

**QuickShare Server** is a lightweight desktop application built with **Python (PyQt6)** that lets you instantly host and share any local folder through a simple HTTP file server — all without touching the command line.

---

## 🖥️ Overview

Tired of typing `python -m http.server` every time you want to share files locally?  
QuickShare Server provides a **modern graphical interface** for that exact purpose.

You can select a folder, start the server with one click, auto-detect free ports, copy the URL, or scan a QR code to access your shared files instantly on any device connected to the same network.

---

## ✨ Features

- 📂 **Host Any Folder** — choose a directory and serve it locally.
- ⚡ **One-Click Start/Stop** — manage your local server easily.
- 🔍 **Auto Port Detection** — automatically find a free port.
- 🔗 **Instant Access URL** — automatically copied to your clipboard.
- 📱 **QR Code Generator** — open on your phone instantly.
- 🌓 **Dark/Light Theme Switch** — easy on the eyes.
- 🧾 **Real-Time Log Viewer** — view connection and request logs.
- 🪟 **System Tray Integration** — minimize and keep it running quietly in the background.

---

## 🧰 Tech Stack

| Component | Description |
|------------|-------------|
| **Language** | Python 3 |
| **GUI Framework** | PyQt6 |
| **HTTP Server** | Built-in `http.server` module |
| **QR Generation** | `qrcode` + `Pillow` |
| **Clipboard** | `pyperclip` |
| **Logging** | Custom threaded logger |

---

## 📦 Installation

### 1️⃣ Clone the repository
```bash
git clone https://github.com/yourusername/QuickShare-Server.git
cd QuickShare-Server
````

### 2️⃣ Create and activate a virtual environment (optional but recommended)

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### 3️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

---

## ▶️ Usage

### Run the app:

```bash
python main.py
```

Then:

1. Select a folder to serve.
2. Click **Start Server**.
3. Copy or scan the URL shown.
4. Access it from any device on the same network.

To stop the server, click **Stop Server** or right-click the **tray icon**.

---

## 📁 Project Structure

```
QuickShare-Server/
│
├── main.py              # Entry point for the application
├── gui.py               # PyQt6 user interface
├── server_manager.py    # Handles server start/stop logic
├── logger_thread.py     # Threaded log handler for subprocess
├── utils.py             # Helper functions (QR, ports, IP, etc.)
├── requirements.txt     # Project dependencies
└── README.md            # Documentation
```

---

## ⚙️ Requirements

* Python 3.9 or newer
* Works on Windows, macOS, and Linux

Install all required dependencies via:

```bash
pip install -r requirements.txt
```

---

## 🧪 Example

Once running, you’ll see something like this:

```
Server running on port 8080
Access URL: http://192.168.0.102:8080/
QR Code generated and displayed
```

Scan the QR code on your phone, and you’ll instantly see your shared files.

---

## 💡 Use Case

* Quickly transfer files between your laptop and phone.
* Host a small local project for testing.
* Share files in your local network without USB or cloud.
* Simplify local development setups.


---

## 📜 License

This project is licensed under the **MIT License** — feel free to modify and distribute it.

---

### 🌐 “Share files. Instantly. Locally.”

```

---<img width="1066" height="792" alt="image" src="https://github.com/user-attachments/assets/048036cc-2969-42dd-acb7-a924d38f1950" />


```
