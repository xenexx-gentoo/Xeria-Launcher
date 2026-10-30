import contextlib
import threading

from PyQt6.QtCore import QThread, pyqtSignal

_shutdown = threading.Event()
_leaked_threads = []
_all_workers = set()
_all_lock = threading.Lock()


def register_worker(w):
    with _all_lock:
        _all_workers.add(w)


def unregister_worker(w):
    with _all_lock:
        _all_workers.discard(w)


def stop_all_workers(timeout_ms=3000):
    _shutdown.set()
    with _all_lock:
        workers = list(_all_workers)
    for w in workers:
        with contextlib.suppress(Exception):
            w.quit()
            if not w.wait(timeout_ms):
                _leaked_threads.append(w)
                w.setParent(None)
    with _all_lock:
        _all_workers.clear()


class Worker(QThread):
    log = pyqtSignal(str, str)
    progress = pyqtSignal(str, int, int, str, str)
    progress_end = pyqtSignal()
    done = pyqtSignal(object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        register_worker(self)
        self.finished.connect(lambda: unregister_worker(self))

    def run(self):
        try:
            if _shutdown.is_set():
                self.done.emit(None)
                return
            r = self.fn(
                *self.args,
                log=self.log.emit,
                progress=self.progress.emit,
                progress_end=self.progress_end.emit,
            )
            self.done.emit(r)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            with contextlib.suppress(Exception):
                self.log.emit("error", f"crashed: {e}")
            self.done.emit(None)
