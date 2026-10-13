# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Асинхронный рендер страниц в отдельном процессе: интерфейс не подвисает при прокрутке."""
import heapq
import itertools
import multiprocessing as mp
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from . import render_proc


class RenderService(QObject):
    rendered = Signal(object, int, int, float, QImage)   # doc_key, gen, page_idx, zoom, image
    _incoming = Signal(object)

    MAX_IN_FLIGHT = 2

    def __init__(self):
        super().__init__()
        self._heap = []
        self._pending = {}            # (key, gen, idx, zoom) -> [prio, alive]
        self._inflight = {}           # rid -> (key, gen, idx, zoom)
        self._rid = itertools.count(1)
        self._counter = itertools.count()
        self._docs = {}               # key -> (gen, bytes) for fallback
        self._fallback_docs = {}
        self._incoming.connect(self._on_msg)
        self.proc = None
        self.conn = None
        self._lock = threading.Lock()
        try:
            ctx = mp.get_context("spawn")
            if sys.executable.lower().endswith("pythonw.exe"):
                ctx.set_executable(sys.executable)
            parent, child = ctx.Pipe()
            self.proc = ctx.Process(target=render_proc.worker, args=(child,), daemon=True)
            self.proc.start()
            self.conn = parent
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception:
            self.proc = None
            self.conn = None
        self._fb_timer = QTimer(self)
        self._fb_timer.setInterval(0)
        self._fb_timer.timeout.connect(self._fallback_step)

    # ---------------------------------------------------------------- документы
    def load(self, key, gen, data):
        self._docs[key] = (gen, data)
        self._fallback_docs.pop(key, None)
        # всё, что ждало старую версию, больше не нужно
        for k, v in list(self._pending.items()):
            if k[0] == key and k[1] != gen:
                v[1] = False
                del self._pending[k]
        if self.conn:
            try:
                with self._lock:
                    self.conn.send(("load", key, gen, data))
            except OSError:
                self.conn = None

    def close(self, key):
        self._docs.pop(key, None)
        self._fallback_docs.pop(key, None)
        if self.conn:
            try:
                with self._lock:
                    self.conn.send(("close", key))
            except OSError:
                pass

    # ---------------------------------------------------------------- запросы
    def request(self, key, gen, idx, zoom, prio):
        k = (key, gen, idx, round(zoom, 4))
        if k in self._pending:
            entry = self._pending[k]
            if prio < entry[0]:
                entry[1] = False
                new = [prio, True]
                self._pending[k] = new
                heapq.heappush(self._heap, (prio, next(self._counter), k, new))
        elif k not in self._inflight.values():
            entry = [prio, True]
            self._pending[k] = entry
            heapq.heappush(self._heap, (prio, next(self._counter), k, entry))
        self._pump()

    def cancel(self, key, keep=None):
        """Снимает все ожидающие запросы документа, кроме набора keep (idx, zoom)."""
        for k, v in list(self._pending.items()):
            if k[0] == key and (keep is None or (k[2], k[3]) not in keep):
                v[1] = False
                del self._pending[k]

    def _pump(self):
        if not self.conn:
            if self._heap and not self._fb_timer.isActive():
                self._fb_timer.start()
            return
        while len(self._inflight) < self.MAX_IN_FLIGHT and self._heap:
            prio, _, k, entry = heapq.heappop(self._heap)
            if not entry[1]:
                continue
            self._pending.pop(k, None)
            rid = next(self._rid)
            self._inflight[rid] = k
            try:
                with self._lock:
                    self.conn.send(("render", rid, k[0], k[1], k[2], k[3]))
            except OSError:
                self.conn = None
                self._inflight.pop(rid, None)
                self._pump()
                return

    def _reader(self):
        while True:
            try:
                msg = self.conn.recv()
            except (EOFError, OSError, AttributeError):
                break
            self._incoming.emit(msg)
        self.conn = None

    def _on_msg(self, msg):
        rid = msg[1]
        k = self._inflight.pop(rid, None)
        if msg[0] == "img" and k:
            _, _, w, h, stride, samples = msg
            img = QImage(samples, w, h, stride, QImage.Format_RGB888).copy()
            self.rendered.emit(k[0], k[1], k[2], k[3], img)
        self._pump()

    # ---------------------------------------------------------------- запасной режим
    def _fallback_step(self):
        import pymupdf
        while self._heap:
            prio, _, k, entry = heapq.heappop(self._heap)
            if not entry[1]:
                continue
            self._pending.pop(k, None)
            key, gen, idx, zoom = k
            d = self._docs.get(key)
            if not d or d[0] != gen:
                continue
            doc = self._fallback_docs.get(key)
            if doc is None or doc[0] != gen:
                doc = (gen, pymupdf.open(stream=d[1], filetype="pdf"))
                self._fallback_docs[key] = doc
            pix = doc[1][idx].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            self.rendered.emit(key, gen, idx, zoom, img)
            return
        self._fb_timer.stop()

    def shutdown(self):
        if self.conn:
            try:
                with self._lock:
                    self.conn.send(None)
            except OSError:
                pass
        if self.proc:
            self.proc.join(0.5)
            if self.proc.is_alive():
                self.proc.terminate()


_service = None


def service():
    global _service
    if _service is None:
        _service = RenderService()
    return _service
