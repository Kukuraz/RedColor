# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Окно одного документа: холст, плавающая панель инструментов, правая колонка, поиск."""
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIntValidator, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsRectItem, QHBoxLayout, QLabel, QLineEdit, QMenu, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import icons
from .organize import OrganizeView
from .toolbar import FloatBar
from .theme import T
from .view import PdfView
from .widgets import IconButton


class RightRail(QFrame):
    def __init__(self, main, doc):
        super().__init__()
        self.setObjectName("rightrail")
        self.setFixedWidth(46)
        self.setStyleSheet(f"#rightrail{{background:{T['bar']};border-left:1px solid {T['border']};}}")
        A = main.A
        v = QVBoxLayout(self)
        v.setContentsMargins(5, 8, 5, 10)
        v.setSpacing(4)
        for aid in ("view.organize", "view.find", "page.insert_blank", "app.quotes"):
            b = IconButton(A[aid].property("icon_name"), A[aid].toolTip(), 18, action=A[aid])
            b.setIcon(A[aid].icon())
            b.setFixedSize(34, 32)
            v.addWidget(b)
        v.addStretch(1)
        self.page_edit = QLineEdit("1")
        self.page_edit.setAlignment(Qt.AlignCenter)
        self.page_edit.setFixedSize(34, 26)
        self.page_edit.setValidator(QIntValidator(1, 99999))
        self.page_edit.returnPressed.connect(lambda: doc.view.go_to_page(int(self.page_edit.text() or 1) - 1))
        v.addWidget(self.page_edit, 0, Qt.AlignHCenter)
        self.total = QLabel("1")
        self.total.setAlignment(Qt.AlignCenter)
        self.total.setStyleSheet(f"color:{T['text2']};font-size:12px")
        v.addWidget(self.total)
        up = IconButton("chevron_up", "Предыдущая страница", 16, action=A["view.prev_page"])
        up.setIcon(icons.icon("chevron_up"))
        dn = IconButton("chevron_down", "Следующая страница", 16, action=A["view.next_page"])
        dn.setIcon(icons.icon("chevron_down"))
        for b in (up, dn):
            b.setFixedSize(34, 26)
            v.addWidget(b)
        v.addSpacing(8)
        for aid, ic in (("page.rotate_cw", "rotate_cw"), ("view.fit_width", "fit_width"), ("view.fit_page", "fit_page"),
                        ("view.zoom_in", "zoom_in"), ("view.zoom_out", "zoom_out")):
            b = IconButton(ic, A[aid].toolTip(), 18, action=A[aid])
            b.setIcon(icons.icon(ic))
            b.setFixedSize(34, 30)
            v.addWidget(b)
        self.zoom_btn = QToolButton()
        self.zoom_btn.setText("100%")
        self.zoom_btn.setFixedSize(40, 24)
        self.zoom_btn.setStyleSheet("font-size:11px;padding:0")
        zm = QMenu(self)
        for z in (50, 75, 100, 125, 150, 200, 300, 400):
            zm.addAction(f"{z}%", lambda z=z: (setattr(doc.view, "fit_mode", None), doc.view.set_zoom(z / 100 * 96 / 72)))
        zm.addSeparator()
        zm.addAction(A["view.fit_width"])
        zm.addAction(A["view.fit_page"])
        zm.addAction(A["view.actual"])
        self.zoom_btn.setMenu(zm)
        self.zoom_btn.setPopupMode(QToolButton.InstantPopup)
        v.addWidget(self.zoom_btn, 0, Qt.AlignHCenter)

    def set_page(self, cur, total):
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(cur + 1))
        self.total.setText(str(total))

    def set_zoom(self, z):
        self.zoom_btn.setText(f"{round(z * 72 / 96 * 100)}%")


class FindBar(QFrame):
    def __init__(self, doc, parent):
        super().__init__(parent)
        self.doc = doc
        self.setObjectName("floatbar")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 4, 4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Найти в документе")
        self.edit.setFixedWidth(220)
        self.edit.returnPressed.connect(self.next)
        self.edit.textChanged.connect(lambda: self._timer.start())
        h.addWidget(self.edit)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{T['text2']}")
        h.addWidget(self.info)
        for ic, fn, tip in (("chevron_up", self.prev, "Предыдущее"), ("chevron_down", self.next, "Следующее"),
                            ("close", self.close_bar, "Закрыть")):
            b = IconButton(ic, tip, 16)
            b.clicked.connect(fn)
            h.addWidget(b)
        self.hits = []
        self.marks = []
        self.idx = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.search)
        self.hide()

    def open(self):
        self.show()
        self.raise_()
        self.adjustSize()
        self.reposition()
        self.edit.setFocus()
        self.edit.selectAll()

    def reposition(self):
        par = self.parentWidget()
        self.move(par.width() - self.width() - 16, 10)

    def clear_marks(self):
        for m in self.marks:
            if m.scene():
                m.scene().removeItem(m)
        self.marks = []

    def search(self):
        self.clear_marks()
        self.hits = []
        self.idx = -1
        q = self.edit.text().strip()
        if not q:
            self.info.setText("")
            return
        model = self.doc.model
        for i, pi in enumerate(model.pages):
            page = model.doc[i]
            rot = page.rotation_matrix if page.rotation else None
            for r in page.search_for(q):
                if rot is not None:
                    r = r * page.rotation_matrix
                m = QGraphicsRectItem(QRectF(r.x0, r.y0, r.width, r.height), pi)
                m.setBrush(QBrush(QColor(255, 210, 0, 90)))
                m.setPen(QPen(Qt.NoPen))
                m.setZValue(-1)
                self.marks.append(m)
                self.hits.append((i, m))
        self.info.setText(f"{len(self.hits)} найдено" if self.hits else "Не найдено")
        if self.hits:
            self.next()

    def _go(self):
        if not self.hits:
            return
        i, m = self.hits[self.idx]
        for _, mm in self.hits:
            mm.setBrush(QBrush(QColor(255, 210, 0, 90)))
        m.setBrush(QBrush(QColor(255, 140, 0, 140)))
        self.doc.view.centerOn(m.sceneBoundingRect().center())
        self.info.setText(f"{self.idx + 1} из {len(self.hits)}")

    def next(self):
        if self.hits:
            self.idx = (self.idx + 1) % len(self.hits)
            self._go()

    def prev(self):
        if self.hits:
            self.idx = (self.idx - 1) % len(self.hits)
            self._go()

    def close_bar(self):
        self.clear_marks()
        self.hits = []
        self.hide()
        self.doc.view.setFocus()


class DocumentWidget(QWidget):
    def __init__(self, model, main):
        super().__init__()
        self.model = model
        self.main = main
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.canvas = QWidget()
        cl = QVBoxLayout(self.canvas)
        cl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack)
        self.view = PdfView(model, main.tools)
        self.stack.addWidget(self.view)
        self.organize = None
        h.addWidget(self.canvas, 1)
        self.rail = RightRail(main, self)
        h.addWidget(self.rail)
        self.floatbar = FloatBar(main, self.canvas)
        self.findbar = FindBar(self, self.canvas)
        self.view.page_changed.connect(self.rail.set_page)
        self.view.zoom_changed.connect(self.rail.set_zoom)
        self.rail.set_page(0, len(model.pages))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.findbar.isVisible():
            self.findbar.reposition()
        self.floatbar.place()

    def in_organize(self):
        return self.organize is not None and self.stack.currentWidget() is self.organize

    def enter_organize(self):
        if self.organize is None:
            self.organize = OrganizeView(self.model, self.main)
            self.organize.open_page.connect(self._open_from_organize)
            self.stack.addWidget(self.organize)
        self.organize.rebuild()
        cur = self.view.current_page()
        if 0 <= cur < self.organize.count():
            self.organize.setCurrentRow(cur)
        self.stack.setCurrentWidget(self.organize)
        self.floatbar.hide()
        self.organize.setFocus()

    def exit_organize(self):
        self.stack.setCurrentWidget(self.view)
        from .toolbar import config as _fb_config
        self.floatbar.setVisible(_fb_config().get("visible", True))
        self.view.setFocus()

    def _open_from_organize(self, i):
        self.main.exit_organize()
        QTimer.singleShot(0, lambda: self.view.go_to_page(i))
