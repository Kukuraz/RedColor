# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Систематизация страниц: сетка миниатюр, перетаскивание, поворот, удаление, вставка."""
from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QListView, QListWidget, QListWidgetItem, QMenu,
                               QStyledItemDelegate, QStyle)

from .render import service
from .theme import T

UID = Qt.UserRole + 1


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.v = view

    def sizeHint(self, opt, idx):
        s = self.v.thumb
        return QSize(s + 36, int(s * 1.3) + 40)

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = opt.rect.adjusted(6, 6, -6, -6)
        uid = idx.data(UID)
        page = self.v.model_.page_by_uid(uid)
        sel = opt.state & QStyle.State_Selected
        hov = opt.state & QStyle.State_MouseOver
        tile = QRectF(r.adjusted(0, 0, 0, -22))
        if sel:
            p.setPen(QPen(QColor(T["accent"]), 2))
            p.setBrush(QColor(197, 220, 250, 235) if T is not None else QColor("#c5dcfa"))
            p.drawRoundedRect(tile, 3, 3)
        elif hov:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 25))
            p.drawRoundedRect(tile, 3, 3)
        if page is not None:
            area = tile.adjusted(10, 10, -10, -10)
            aw, ah = area.width(), area.height()
            sc = min(aw / page.w, ah / page.h)
            w, h = page.w * sc, page.h * sc
            pr = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
            pix = page.low or page.pix
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRect(pr.translated(1.5, 2))
            if pix is not None:
                p.drawPixmap(pr, pix, QRectF(pix.rect()))
            else:
                p.fillRect(pr, QColor("#ffffff"))
            if page.overlay_items():
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ff3b30"))
                p.drawEllipse(QRectF(pr.right() - 9, pr.top() + 3, 6, 6))
        p.setPen(QColor(T["text"]))
        p.drawText(QRect(r.left(), r.bottom() - 20, r.width(), 20), Qt.AlignCenter, str(idx.row() + 1))
        p.restore()


class OrganizeView(QListWidget):
    open_page = Signal(int)
    selection_info = Signal(int)

    def __init__(self, model, ctx, parent=None):
        super().__init__(parent)
        self.setObjectName("thumbs")
        self.model_ = model
        self.ctx = ctx
        self.thumb = 150
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setItemDelegate(ThumbDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.model().rowsMoved.connect(self._moved)
        self.itemDoubleClicked.connect(lambda it: self.open_page.emit(self.row(it)))
        self.itemSelectionChanged.connect(lambda: self.selection_info.emit(len(self.selectedItems())))
        model.structure_changed.connect(self.rebuild)
        model.page_pixmap.connect(lambda uid: self.viewport().update())
        self._rebuilding = False
        self.rebuild()

    def set_thumb(self, s):
        self.thumb = s
        self.setGridSize(QSize())
        self.reset()
        self.rebuild()

    def rebuild(self):
        sel = {it.data(UID) for it in self.selectedItems()}
        self._rebuilding = True
        self.clear()
        for i, p in enumerate(self.model_.pages):
            it = QListWidgetItem()
            it.setData(UID, p.uid)
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)
            self.addItem(it)
            if p.uid in sel:
                it.setSelected(True)
        self._rebuilding = False
        self.request_thumbs()

    def request_thumbs(self):
        for i, p in enumerate(self.model_.pages):
            if p.low is None:
                service().request(self.model_.key, self.model_.gen, i, 0.25, 30 + i * 0.01)

    def selected_indices(self):
        return sorted(self.row(it) for it in self.selectedItems())

    def _moved(self, *a):
        if self._rebuilding:
            return
        order = [self.item(i).data(UID) for i in range(self.count())]
        new_items = [self.model_.page_by_uid(u) for u in order]
        QTimer.singleShot(0, lambda: self.model_.move_pages(new_items))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.ctx.delete_pages(self.selected_indices())
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            rows = self.selected_indices()
            if rows:
                self.open_page.emit(rows[0])
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y()
            self.set_thumb(max(70, min(400, int(self.thumb * (1.12 if d > 0 else 1 / 1.12)))))
            return
        super().wheelEvent(e)

    def _menu(self, pos):
        rows = self.selected_indices()
        m = QMenu(self)
        if rows:
            m.addAction("Повернуть вправо", lambda: self.ctx.rotate_pages(rows, 90))
            m.addAction("Повернуть влево", lambda: self.ctx.rotate_pages(rows, -90))
            m.addAction("Удалить", lambda: self.ctx.delete_pages(rows))
            m.addAction("Извлечь…", lambda: self.ctx.extract_pages(rows))
            m.addSeparator()
        at = (rows[-1] + 1) if rows else self.count()
        m.addAction("Вставить пустую страницу", lambda: self.ctx.insert_blank_page(at))
        m.addAction("Вставить из файла…", lambda: self.ctx.insert_from_file(at))
        bm = m.addMenu("Вставить бланк")
        self.ctx.fill_blank_menu(bm, at)
        m.exec(self.viewport().mapToGlobal(pos))
