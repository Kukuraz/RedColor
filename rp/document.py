# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Модель документа: PDF (PyMuPDF) + страницы на сцене + история отмены."""
import itertools
import json
import os
from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from .config import APP_NAME, APP_VERSION, AUTHOR
from .items import BoxItem
from .render import service
from .theme import T

pymupdf.TOOLS.mupdf_display_errors(False)
_uid = itertools.count(1)
_doc_key = itertools.count(1)
PAGE_GAP = 14.0
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".jfif"}


class PageItem(QGraphicsItem):
    def __init__(self, w, h):
        super().__init__()
        self.uid = next(_uid)
        self.w, self.h = w, h
        self.pix = None
        self.pix_zoom = 0.0
        self.low = None
        self.low_zoom = 0.0
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, False)
        self.setZValue(0)

    def boundingRect(self):
        return QRectF(-4, -3, self.w + 8, self.h + 9)

    def page_rect(self):
        return QRectF(0, 0, self.w, self.h)

    def paint(self, p, opt, widget=None):
        s = p.worldTransform().m11() or 1.0
        sh = QColor(T["page_shadow"])
        for i, a in ((3, 40), (2, 60), (1, 90)):
            sh.setAlpha(a)
            d = i / s
            p.fillRect(QRectF(-d, -d * 0.5, self.w + 2 * d, self.h + 2.5 * d), sh)
        r = QRectF(0, 0, self.w, self.h)
        pix = self.pix or self.low
        if pix is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(r, pix, QRectF(pix.rect()))
        else:
            p.fillRect(r, QColor("#ffffff"))

    def overlay_items(self):
        return [c for c in self.childItems() if isinstance(c, BoxItem)]

    def set_size(self, w, h):
        self.prepareGeometryChange()
        self.w, self.h = w, h

    def drop_pixmaps(self, keep_low=False):
        self.pix = None
        self.pix_zoom = 0.0
        if not keep_low:
            self.low = None
            self.low_zoom = 0.0
        self.update()


# =========================================================================== команды отмены
class FuncCmd(QUndoCommand):
    def __init__(self, text, redo, undo, skip_first=False):
        super().__init__(text)
        self._r, self._u = redo, undo
        self._skip = skip_first

    def redo(self):
        if self._skip:
            self._skip = False
            return
        self._r()

    def undo(self):
        self._u()


class StateCmd(QUndoCommand):
    def __init__(self, items, before, after, text="Изменение"):
        super().__init__(text)
        self.items, self.before, self.after = list(items), list(before), list(after)
        self._first = True

    def redo(self):
        if self._first:
            self._first = False
            return
        for it, st in zip(self.items, self.after):
            it.apply_state(st)

    def undo(self):
        for it, st in zip(self.items, self.before):
            it.apply_state(st)


# =========================================================================== модель
class DocModel(QObject):
    layout_changed = Signal()
    structure_changed = Signal()
    page_pixmap = Signal(int)          # uid
    modified_changed = Signal(bool)
    path_changed = Signal(str)

    def __init__(self, path=None, data=None, title=None):
        super().__init__()
        self.key = next(_doc_key)
        self.gen = 0
        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(200)
        self.undo.cleanChanged.connect(lambda c: self.modified_changed.emit(not c))
        self.path = str(path) if path else None
        self.title = title or (Path(path).name if path else "Без имени.pdf")
        self.pages = []
        if data is None and path:
            data = Path(path).read_bytes()
        self.doc = self._open_bytes(data, Path(path).suffix.lower() if path else ".pdf")
        restored = self._extract_layers()
        for pg in self.doc:
            r = pg.rect
            self._add_page_item(PageItem(r.width, r.height))
        for i, states in restored.items():
            self._restore_items(self.pages[i], states)
        self.relayout()
        service().rendered.connect(self._on_rendered)
        self.sync_render(initial_bytes=data if (self._opened_pdf and not restored) else None)

    def _open_bytes(self, data, ext):
        self._opened_pdf = True
        if ext in IMG_EXT:
            img = pymupdf.open(stream=data, filetype=ext.lstrip("."))
            pdf = pymupdf.open("pdf", img.convert_to_pdf())
            self._opened_pdf = False
            return pdf
        d = pymupdf.open(stream=data, filetype="pdf")
        if d.is_encrypted:
            d.authenticate("")
        return d

    # ---------------------------------------------------------------- редактируемый слой RedColor
    def _extract_layers(self):
        """Находит сохранённые RedColor-пометки: убирает их слой из страницы и возвращает описания объектов."""
        out = {}
        for i, page in enumerate(self.doc):
            try:
                t, val = self.doc.xref_get_key(page.xref, "RedColorItems")
            except Exception:
                continue
            if t != "xref":
                continue
            try:
                ixref = int(val.split()[0])
                states = json.loads(self.doc.xref_stream(ixref).decode("utf-8"))
                t2, v2 = self.doc.xref_get_key(page.xref, "RedColorContent")
                cxref = int(v2.split()[0]) if t2 == "xref" else None
                if cxref:
                    rest = [x for x in page.get_contents() if x != cxref]
                    if rest:
                        self.doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in rest) + "]")
                    else:
                        self.doc.xref_set_key(page.xref, "Contents", "null")
                self.doc.xref_set_key(page.xref, "RedColorItems", "null")
                self.doc.xref_set_key(page.xref, "RedColorContent", "null")
                out[i] = states.get("items", [])
            except Exception as e:
                print("layer restore error:", e)
        return out

    def _restore_items(self, pi, states):
        from .items import create_item
        for st in states:
            try:
                it = create_item(st)
            except Exception as e:
                print("item restore error:", e)
                it = None
            if it is not None:
                it.setParentItem(pi)

    # ---------------------------------------------------------------- служебное
    def _add_page_item(self, pi, index=None):
        if index is None:
            self.pages.append(pi)
        else:
            self.pages.insert(index, pi)
        if pi.scene() is None:
            self.scene.addItem(pi)

    def relayout(self):
        maxw = max((p.w for p in self.pages), default=600)
        y = PAGE_GAP
        for p in self.pages:
            p.setPos((maxw - p.w) / 2, y)
            y += p.h + PAGE_GAP
        m = 8
        self.scene.setSceneRect(QRectF(-m, 0, maxw + 2 * m, y + PAGE_GAP))
        self.layout_changed.emit()

    def sync_render(self, initial_bytes=None):
        self.gen += 1
        data = initial_bytes if initial_bytes is not None else self.doc.tobytes(garbage=0, deflate=False)
        service().load(self.key, self.gen, data)

    def _structure_done(self):
        self.relayout()
        self.sync_render()
        self.structure_changed.emit()

    def _on_rendered(self, key, gen, idx, zoom, img):
        if key != self.key or gen != self.gen or idx >= len(self.pages):
            return
        pi = self.pages[idx]
        pix = QPixmap.fromImage(img)
        if zoom <= 0.35:
            if zoom >= pi.low_zoom:
                pi.low, pi.low_zoom = pix, zoom
        elif zoom >= pi.pix_zoom * 0.99 or pi.pix is None:
            pi.pix, pi.pix_zoom = pix, zoom
        pi.update()
        self.page_pixmap.emit(pi.uid)

    def index_of(self, pi):
        return self.pages.index(pi)

    def page_by_uid(self, uid):
        for p in self.pages:
            if p.uid == uid:
                return p
        return None

    def page_at(self, scene_pos):
        for p in self.pages:
            if p.sceneBoundingRect().adjusted(4, 3, -4, -9).contains(scene_pos):
                return p
        return None

    def nearest_page(self, scene_pos):
        best, bd = None, 1e18
        for p in self.pages:
            r = p.sceneBoundingRect()
            d = 0 if r.top() <= scene_pos.y() <= r.bottom() else min(abs(r.top() - scene_pos.y()), abs(r.bottom() - scene_pos.y()))
            if d < bd:
                best, bd = p, d
        return best

    def has_overlays(self):
        return any(p.overlay_items() for p in self.pages)

    def close(self):
        service().close(self.key)
        try:
            service().rendered.disconnect(self._on_rendered)
        except (RuntimeError, TypeError):
            pass
        self.doc.close()

    # ---------------------------------------------------------------- поворот
    def _rotate(self, uids, delta):
        for uid in uids:
            pi = self.page_by_uid(uid)
            i = self.index_of(pi)
            pg = self.doc[i]
            pg.set_rotation((pg.rotation + delta) % 360)
            steps = (delta // 90) % 4
            for _ in range(steps):
                ow, oh = pi.w, pi.h
                for it in pi.overlay_items():
                    p = it.pos()
                    it.setPos(oh - p.y(), p.x())
                    it.setRotation((it.rotation() + 90) % 360)
                pi.set_size(oh, ow)
            pi.drop_pixmaps()
        self._structure_done()

    def rotate_pages(self, indices, delta):
        uids = [self.pages[i].uid for i in indices if 0 <= i < len(self.pages)]
        if not uids:
            return
        delta %= 360
        self.undo.push(FuncCmd("Поворот страниц", lambda: self._rotate(uids, delta),
                               lambda: self._rotate(uids, (360 - delta) % 360)))

    # ---------------------------------------------------------------- удаление
    def delete_pages(self, indices):
        indices = sorted(set(i for i in indices if 0 <= i < len(self.pages)))
        if not indices or len(indices) >= len(self.pages):
            return False
        store = pymupdf.open()
        items = []
        for i in indices:
            store.insert_pdf(self.doc, from_page=i, to_page=i)
            items.append(self.pages[i])

        def redo():
            idx = [self.index_of(p) for p in items]
            self.doc.delete_pages(idx)
            for p in items:
                self.pages.remove(p)
                self.scene.removeItem(p)
            self._structure_done()

        def undo():
            for k, (i, p) in enumerate(zip(indices, items)):
                self.doc.insert_pdf(store, from_page=k, to_page=k, start_at=i)
                self._add_page_item(p, i)
            self._structure_done()

        self.undo.push(FuncCmd("Удаление страниц", redo, undo))
        return True

    # ---------------------------------------------------------------- вставка
    def insert_pdf(self, src, at, text="Вставка страниц", macro_items=None):
        """src — fitz.Document. Вставляет все его страницы на позицию at. Возвращает список PageItem."""
        store = pymupdf.open()
        store.insert_pdf(src)
        new_items = [PageItem(pg.rect.width, pg.rect.height) for pg in store]
        n = len(new_items)

        def redo():
            self.doc.insert_pdf(store, start_at=at)
            for k, p in enumerate(new_items):
                self._add_page_item(p, at + k)
            self._structure_done()

        def undo():
            self.doc.delete_pages(list(range(at, at + n)))
            for p in new_items:
                self.pages.remove(p)
                self.scene.removeItem(p)
            self._structure_done()

        self.undo.push(FuncCmd(text, redo, undo))
        return new_items

    def insert_blank_page(self, at, w=None, h=None):
        ref = self.pages[min(max(at - 1, 0), len(self.pages) - 1)] if self.pages else None
        w = w or (ref.w if ref else 595)
        h = h or (ref.h if ref else 842)
        tmp = pymupdf.open()
        tmp.new_page(width=w, height=h)
        return self.insert_pdf(tmp, at, "Пустая страница")

    def insert_file(self, path, at):
        ext = Path(path).suffix.lower()
        if ext in IMG_EXT:
            img = pymupdf.open(path)
            src = pymupdf.open("pdf", img.convert_to_pdf())
        else:
            src = pymupdf.open(path)
        return self.insert_pdf(src, at, f"Вставка: {Path(path).name}")

    # ---------------------------------------------------------------- порядок
    def _reorder(self, new_items):
        order = [self.index_of(p) for p in new_items]
        self.doc.select(order)
        self.pages = list(new_items)
        self._structure_done()

    def move_pages(self, new_items):
        old = list(self.pages)
        new = list(new_items)
        if old == new:
            return
        self.undo.push(FuncCmd("Порядок страниц", lambda: self._reorder(new), lambda: self._reorder(old)))

    def extract_pages(self, indices, path):
        out = self.build_output(sorted(indices))
        out.save(path, garbage=3, deflate=True)
        out.close()

    # ---------------------------------------------------------------- объекты
    def add_items(self, pairs, text="Добавление", already=False):
        pairs = list(pairs)

        def redo():
            for page, it in pairs:
                it.setParentItem(page)
                it.setVisible(True)

        def undo():
            for page, it in pairs:
                it.setSelected(False)
                if it.scene():
                    it.scene().removeItem(it)
                it.setParentItem(None)

        if not already:
            redo()
        self.undo.push(FuncCmd(text, redo, undo, skip_first=True))

    def remove_items(self, items, text="Удаление"):
        pairs = [(it.parentItem(), it) for it in items if it.parentItem() is not None]
        if not pairs:
            return

        def redo():
            for page, it in pairs:
                it.setSelected(False)
                if it.scene():
                    it.scene().removeItem(it)
                it.setParentItem(None)

        def undo():
            for page, it in pairs:
                it.setParentItem(page)

        self.undo.push(FuncCmd(text, redo, undo))

    def push_state(self, items, before, after, text="Изменение"):
        if before == after:
            return
        self.undo.push(StateCmd(items, before, after, text))

    # ---------------------------------------------------------------- сохранение
    def build_output(self, indices=None, editable=True):
        out = pymupdf.open(stream=self.doc.tobytes(garbage=0), filetype="pdf")
        for i, pi in enumerate(self.pages):
            items = pi.overlay_items()
            if not items:
                continue
            page = out[i]
            r = page.rect                       # отображаемая ориентация
            target = r * page.derotation_matrix   # та же область в координатах неповёрнутой страницы
            target.normalize()
            ov = pymupdf.open()
            op = ov.new_page(width=r.width, height=r.height)
            items = sorted(items, key=lambda x: x.zValue())
            for it in items:
                try:
                    it.bake(op)
                except Exception as e:  # один объект не должен ломать сохранение
                    print("bake error:", e)
            before = set(page.get_contents())
            page.show_pdf_page(target, ov, 0, overlay=True, keep_proportion=False, rotate=page.rotation)
            ov.close()
            added = [x for x in page.get_contents() if x not in before]
            added = [x for x in added if b"Do" in out.xref_stream(x)]
            if editable and len(added) == 1:
                try:
                    states = {"v": 1, "items": [it.export_state() for it in items]}
                    sx = out.get_new_xref()
                    out.update_object(sx, "<<>>")
                    out.update_stream(sx, json.dumps(states, ensure_ascii=False).encode("utf-8"))
                    out.xref_set_key(page.xref, "RedColorItems", f"{sx} 0 R")
                    out.xref_set_key(page.xref, "RedColorContent", f"{added[0]} 0 R")
                except Exception as e:
                    print("layer save error:", e)
        if indices is not None:
            out.select(indices)
        try:
            out.subset_fonts()
        except Exception:
            pass
        try:
            meta = dict(out.metadata or {})
            meta["creator"] = f"{APP_NAME} {APP_VERSION} — {AUTHOR}"
            out.set_metadata(meta)
        except Exception:
            pass
        return out

    def save(self, path):
        """Сохраняет через временный файл. Если файл занят другой программой (например, открыт
        в Adobe Acrobat) — несколько попыток, затем FileLockedError; временный файл удаляется."""
        import time
        out = self.build_output()
        tmp = str(path) + ".redcolor.tmp"
        try:
            out.save(tmp, garbage=3, deflate=True)
        finally:
            out.close()
        last = None
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                last = None
                break
            except PermissionError as e:     # занят (Acrobat, синхронизация OneDrive и т.п.)
                last = e
                time.sleep(0.25 * (attempt + 1))
        if last is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise FileLockedError(str(path)) from last
        self.path = str(path)
        self.title = Path(path).name
        self.undo.setClean()
        self.path_changed.emit(self.path)

    # ---------------------------------------------------------------- «1» в комментариях бланков
    def remove_comment_ones(self):
        """Убирает красные «1» в поле «Комментарий эксперта» на всех бланках документа (с отменой)."""
        from .blanks import comment_ones, remove_comment_ones
        targets = []
        for i, pg in enumerate(self.doc):
            try:
                if comment_ones(pg):
                    targets.append(self.pages[i])
            except Exception as e:
                print("ones scan error:", e)
        if not targets:
            return 0
        store = pymupdf.open()
        for pi in targets:
            i = self.index_of(pi)
            store.insert_pdf(self.doc, from_page=i, to_page=i)
        count = [0]

        def swap_from(src_doc, k, pi):
            i = self.index_of(pi)
            self.doc.delete_page(i)
            self.doc.insert_pdf(src_doc, from_page=k, to_page=k, start_at=i)

        def redo():
            count[0] = 0
            for pi in targets:
                count[0] += remove_comment_ones(self.doc[self.index_of(pi)])
                pi.drop_pixmaps()
            self.sync_render()
            self.structure_changed.emit()

        def undo():
            for k, pi in enumerate(targets):
                swap_from(store, k, pi)
                pi.drop_pixmaps()
            self.sync_render()
            self.structure_changed.emit()

        self.undo.push(FuncCmd("Убраны «1» в комментариях бланков", redo, undo))
        return count[0]


class FileLockedError(Exception):
    """Файл занят другой программой."""
