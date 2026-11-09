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
        self._epoch = 0                  # номер запуска процесса рендера
        self._restarts = []              # время перезапусков (защита от бесконечного цикла)
        self._bad = {}                   # (key, gen, idx) -> сколько раз страница роняла рендер
        self._fb_timer = QTimer(self)
        self._fb_timer.setInterval(0)
        self._fb_timer.timeout.connect(self._fallback_step)
        self._start_process()

    def _start_process(self):
        try:
            ctx = mp.get_context("spawn")
            if sys.executable.lower().endswith("pythonw.exe"):
                ctx.set_executable(sys.executable)
            parent, child = ctx.Pipe()
            self.proc = ctx.Process(target=render_proc.worker, args=(child,), daemon=True)
            self.proc.start()
            child.close()
            self.conn = parent
            self._epoch += 1
            threading.Thread(target=self._reader, args=(parent, self._epoch), daemon=True).start()
            for key, (gen, data) in list(self._docs.items()):
                with self._lock:
                    parent.send(("load", key, gen, data))
            return True
        except Exception as e:
            print("render process start failed:", e, file=sys.stderr)
            self.proc = None
            self.conn = None
            return False

    def _restart(self):
        """Процесс рендера упал (нехватка памяти, «битый» PDF): перезапуск без потери работы."""
        import time
        now = time.time()
        self._restarts = [t for t in self._restarts if now - t < 60] + [now]
        lost = list(self._inflight.values())
        self._inflight.clear()
        for k in lost:                   # эти страницы были в работе при сбое
            bk = k[:3]
            self._bad[bk] = self._bad.get(bk, 0) + 1
        try:
            if self.proc is not None and self.proc.is_alive():
                self.proc.terminate()
        except Exception:
            pass
        if self.conn is not None:
            self.conn.close()
        self.conn = None
        self.proc = None
        if len(self._restarts) > 5:
            print("render process keeps failing — rendering paused for problem pages", file=sys.stderr)
        if self._start_process():
            for k in lost:
                if self._bad.get(k[:3], 0) < 2:
                    entry = [0, True]
                    self._pending[k] = entry
                    heapq.heappush(self._heap, (0, next(self._counter), k, entry))
        self._pump()

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
        self.cancel(key)
        self._bad = {k: v for k, v in self._bad.items() if k[0] != key}
        if self.conn:
            try:
                with self._lock:
                    self.conn.send(("close", key))
            except OSError:
                pass

    # ---------------------------------------------------------------- запросы
    def request(self, key, gen, idx, zoom, prio):
        k = (key, gen, idx, round(zoom, 4))
        if self._bad.get(k[:3], 0) >= 2:     # страница дважды роняла рендер — не пытаемся снова
            return
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
        if len(self._heap) > max(128, 2 * len(self._pending)):
            self._heap = [entry for entry in self._heap if entry[3][1]]
            heapq.heapify(self._heap)

    def _pump(self):
        if not self.conn:
            # рисуем в основном процессе, только если отдельный процесс вообще не запускается
            if self.proc is None and self._heap and not self._fb_timer.isActive():
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
            except (OSError, ValueError):
                self._inflight.pop(rid, None)
                self._incoming.emit(("dead", self._epoch))
                return

    def _reader(self, conn, epoch):
        """Поток приёма картинок. Любая ошибка (обрыв, нехватка памяти) — сигнал на перезапуск процесса."""
        while True:
            try:
                msg = conn.recv()
            except BaseException as e:  # noqa: BLE001 — поток не должен умирать молча
                if not isinstance(e, (EOFError, OSError)):
                    print("render reader error:", type(e).__name__, e, file=sys.stderr)
                self._incoming.emit(("dead", epoch))
                return
            self._incoming.emit(msg)

    def _on_msg(self, msg):
        if msg[0] == "dead":
            if msg[1] == self._epoch and not getattr(self, "_shutting_down", False):
                self._restart()
            return
        rid = msg[1]
        k = self._inflight.pop(rid, None)
        if msg[0] == "img" and k:
            try:
                _, _, w, h, stride, samples = msg
                img = QImage(samples, w, h, stride, QImage.Format_RGB888).copy()
                self.rendered.emit(k[0], k[1], k[2], k[3], img)
            except MemoryError:
                print("render: not enough memory for page image", file=sys.stderr)
        elif msg[0] == "err" and k:
            bk = k[:3]
            self._bad[bk] = self._bad.get(bk, 0) + 1
            print("render error:", msg[2] if len(msg) > 2 else "", file=sys.stderr)
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
        self._shutting_down = True
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
                self.proc.join(0.5)
        if self.conn:
            self.conn.close()
            self.conn = None


_service = None


def service():
    global _service
    if _service is None:
        _service = RenderService()
    return _service
