import sys
import subprocess
from utils import find_free_port, is_port_free


class ServerManager:
    def __init__(self):
        self.process = None

    def start_server(self, folder, port):
        if not is_port_free(port):
            port = find_free_port(8000)

        cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"]

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=folder,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            return self.process
        except Exception as e:
            print("Error starting server:", e)
            return None

    def stop_server(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=2)
            self.process = None
