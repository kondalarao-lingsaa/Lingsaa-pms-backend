import threading
import time


class ReaptedTimer:
    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.running = False
        self.thread = None
        self.result = None

    def _run(self):
        while self.running:
            self.result = self.function()
            time.sleep(self.interval)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
