# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Подписи и инициалы: библиотека PNG (прозрачный фон), создание рисованием, текстом или из картинки."""
import json
import time
import uuid

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from . import fonts
from .config import SIG_DIR
from .items import _png_bytes
from .theme import T

INDEX = SIG_DIR / "index.json"


class SignatureStore:
    def __init__(self):
        self.items = []
        self.load()

    def load(self):
        try:
            self.items = [x for x in json.loads(INDEX.read_text(encoding="utf-8"))
                          if (SIG_DIR / x["file"]).exists()]
        except (OSError, ValueError):
            self.items = []

    def save_index(self):
        INDEX.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, png, name, kind="signature"):
        sid = uuid.uuid4().hex[:10]
        fn = f"{sid}.png"
        (SIG_DIR / fn).write_bytes(png)
        self.items.append({"id": sid, "name": name, "file": fn, "kind": kind, "created": time.time()})
        self.save_index()
        return sid

    def remove(self, sid):
        for x in list(self.items):
            if x["id"] == sid:
                self.items.remove(x)
                try:
                    (SIG_DIR / x["file"]).unlink()
                except OSError:
                    pass
        self.save_index()

    def rename(self, sid, name):
        for x in self.items:
            if x["id"] == sid:
                x["name"] = name
        self.save_index()

    def data(self, sid):
        for x in self.items:
            if x["id"] == sid:
                return (SIG_DIR / x["file"]).read_bytes()
        return None

    def get(self, sid):
        return next((x for x in self.items if x["id"] == sid), None)


STORE = SignatureStore()


def _arr(img):
    import numpy as np
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
    return img, buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)


def crop_alpha(img, margin=6):
    import numpy as np
    img, a = _arr(img)
    ys, xs = np.nonzero(a[..., 3] > 10)
    if len(xs) == 0:
        return img
    r = QRectF(xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
    r = r.adjusted(-margin, -margin, margin, margin).toRect()
    return img.copy(r.intersected(img.rect()))


class DrawPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 220)
        self.strokes = []
        self.width_px = 3.0
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.strokes = []
        self.update()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            self.strokes[-1].append(e.position())
            self.update()

    def _path(self, s, scale=1.0):
        p = QPainterPath()
        pts = [QPointF(q.x() * scale, q.y() * scale) for q in s]
        p.moveTo(pts[0])
        if len(pts) == 1:
            p.lineTo(pts[0] + QPointF(0.1, 0.1))
        for i in range(1, len(pts) - 1):
            p.quadTo(pts[i], (pts[i] + pts[i + 1]) / 2)
        if len(pts) > 1:
            p.lineTo(pts[-1])
        return p

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c8c8c8"), 1, Qt.DashLine))
        y = self.height() * 0.72
        p.drawLine(QPointF(20, y), QPointF(self.width() - 20, y))
        p.setPen(QPen(QColor("#111111"), self.width_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            p.drawPath(self._path(s))
        p.end()

    def image(self):
        if not self.strokes:
            return None
        sc = 4.0
        img = QImage(int(self.width() * sc), int(self.height() * sc), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#000000"), self.width_px * sc, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            p.drawPath(self._path(s, sc))
        p.end()
        return crop_alpha(img, 12)


def text_image(text, family, italic=False):
    f = fonts.make_qfont(family, 120, False, italic)
    from PySide6.QtGui import QFontMetricsF
    fm = QFontMetricsF(f)
    w = int(fm.horizontalAdvance(text) + 80)
    h = int(fm.height() + 80)
    img = QImage(max(w, 10), max(h, 10), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor("#000000"))
    p.drawText(QPointF(40, 40 + fm.ascent()), text)
    p.end()
    return crop_alpha(img, 10)


def remove_background(img, threshold=200):
    import numpy as np
    img, a = _arr(img)
    h, w = a.shape[:2]
    lum = a[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    alpha = np.clip((threshold - lum) / max(threshold, 1) * 255 * 2.2, 0, 255) * (a[..., 3] / 255.0)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., 3] = alpha.astype(np.uint8)
    q = QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    return crop_alpha(q, 6)


class SignatureDialog(QDialog):
    def __init__(self, kind="signature", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("Создать подпись" if kind == "signature" else "Создать инициалы")
        self.resize(640, 420)
        v = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Название:"))
        self.name = QLineEdit("Подпись" if kind == "signature" else "Инициалы")
        name_row.addWidget(self.name, 1)
        v.addLayout(name_row)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        # рисовать
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        self.pad = DrawPad()
        l1.addWidget(self.pad, 1)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Толщина"))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(1, 12)
        sl.setValue(3)
        sl.valueChanged.connect(lambda v: (setattr(self.pad, "width_px", float(v)), self.pad.update()))
        r1.addWidget(sl)
        cl = QPushButton("Очистить")
        cl.clicked.connect(self.pad.clear)
        r1.addWidget(cl)
        l1.addLayout(r1)
        self.tabs.addTab(w1, "Нарисовать")
        # ввести
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        self.text = QLineEdit("МБ" if kind != "signature" else "")
        self.text.setPlaceholderText("Введите подпись")
        l2.addWidget(self.text)
        self.font = QComboBox()
        fav, rest = fonts.families()
        pretty = [f for f in fav + rest if f in fonts.PRETTY] + ["Times New Roman", "Minion Pro", "Georgia"]
        others = [f for f in fav + rest if f not in pretty]
        self.font.addItems([f for f in pretty if fonts.exists(f)] + others)
        l2.addWidget(self.font)
        self.preview = QLabel()
        self.preview.setMinimumHeight(150)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#ffffff;border-radius:6px;")
        l2.addWidget(self.preview, 1)
        self.text.textChanged.connect(self._prev)
        self.font.currentTextChanged.connect(self._prev)
        self.tabs.addTab(w2, "Ввести")
        # картинка
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        b = QPushButton("Выбрать изображение…")
        b.clicked.connect(self._load_img)
        l3.addWidget(b)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Убрать фон светлее"))
        self.thr = QSlider(Qt.Horizontal)
        self.thr.setRange(100, 250)
        self.thr.setValue(200)
        self.thr.sliderReleased.connect(self._prev_img)
        r3.addWidget(self.thr)
        l3.addLayout(r3)
        self.img_prev = QLabel("Изображение не выбрано")
        self.img_prev.setAlignment(Qt.AlignCenter)
        self.img_prev.setMinimumHeight(150)
        self.img_prev.setStyleSheet("background:#ffffff;border-radius:6px;color:#777;")
        l3.addWidget(self.img_prev, 1)
        self.tabs.addTab(w3, "Изображение")
        self._src_img = None
        self._img_result = None
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Сохранить")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.sid = None
        self._prev()

    def _prev(self):
        t = self.text.text().strip()
        if not t:
            self.preview.clear()
            return
        img = text_image(t, self.font.currentText())
        pm = QPixmap.fromImage(img).scaled(560, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)

    def _load_img(self):
        p, _ = QFileDialog.getOpenFileName(self, "Изображение подписи", "", "Изображения (*.png *.jpg *.jpeg *.bmp)")
        if p:
            img = QImage(p)
            if img.width() > 1400:
                img = img.scaledToWidth(1400, Qt.SmoothTransformation)
            self._src_img = img
            self._prev_img()

    def _prev_img(self):
        if self._src_img is None:
            return
        self._img_result = remove_background(self._src_img, self.thr.value())
        self.img_prev.setPixmap(QPixmap.fromImage(self._img_result).scaled(560, 150, Qt.KeepAspectRatio,
                                                                           Qt.SmoothTransformation))

    def _ok(self):
        tab = self.tabs.currentIndex()
        img = None
        if tab == 0:
            img = self.pad.image()
        elif tab == 1 and self.text.text().strip():
            img = text_image(self.text.text().strip(), self.font.currentText())
        elif tab == 2:
            img = self._img_result
        if img is None:
            return
        self.sid = STORE.add(_png_bytes(img), self.name.text().strip() or "Подпись", self.kind)
        self.accept()


def thumb(sid, color="#ff0000", size=QSize(180, 48)):
    data = STORE.data(sid)
    if not data:
        return QPixmap()
    img = QImage.fromData(data)
    from .items import tinted
    img = tinted(img, color)
    return QPixmap.fromImage(img).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
