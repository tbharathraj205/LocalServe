import threading


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

        for line in self.process.stdout:
            self.q.put(("OUT", line.strip()))
        for err in self.process.stderr:
            self.q.put(("ERR", err.strip()))

    def stop(self):
        self._stop.set()
