"""File desktop pour le bac mono-instance."""

from collections import deque
from concurrent.futures import Future
from threading import Lock, Thread


class DesktopJobs:
    def __init__(self):
        self.interactive = deque()
        self.maintenance = deque()
        self.lock = Lock()
        self.worker = None
        self.working_in_background = False

    def submit(self, operation, *, background=False):
        with self.lock:
            return self.enqueue(operation, self.maintenance if background else self.interactive)

    def submit_if_idle(self, operation):
        with self.lock:
            if self.worker is not None:
                return None
            return self.enqueue(operation, self.maintenance)

    def interactive_pending(self):
        with self.lock:
            return bool(self.interactive)

    def enqueue(self, operation, queue):
        result = Future()
        queue.append((result, operation))
        if self.worker is None:
            self.worker = Thread(target=self.run, name="Akasha Windows Sandbox")
            self.worker.start()
        return result

    def run(self):
        while True:
            with self.lock:
                queue = self.interactive or self.maintenance
                self.working_in_background = bool(queue) and queue is self.maintenance
                if not queue:
                    self.worker = None
                    return
                job = queue.popleft()
            self.execute(job)

    def checkpoint(self, on_wait):
        """Exécute la file interactive avant que l'évolution reprenne le bac."""
        with self.lock:
            pending = bool(self.interactive)
        if not pending:
            return
        on_wait()
        while True:
            with self.lock:
                if not self.interactive:
                    return
                job = self.interactive.popleft()
            self.execute(job)

    @staticmethod
    def execute(job):
        result, operation = job
        if result.set_running_or_notify_cancel():
            try:
                value = operation()
            except Exception as error:
                result.set_exception(error)
            else:
                result.set_result(value)
