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
        self.undo.cleanChanged.connect(self._clean_changed)
        self.closed = False
        self.last_save_strategy = None
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
        untouched = self._opened_pdf and not restored
        self.sync_render(initial_bytes=data if untouched else None)
        # исходные байты, пока документ не меняли: сохраняем их как есть, без пересборки библиотекой
        self._src_bytes = data if untouched else None

    def _clean_changed(self, clean):
        if not self.closed:
            try:
                self.modified_changed.emit(not clean)
            except RuntimeError:
                pass

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
        if initial_bytes is None:
            self._src_bytes = None          # документ изменён — при сохранении берём его новую версию
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
        self.closed = True
        service().close(self.key)
        for sig, slot in ((service().rendered, self._on_rendered), (self.undo.cleanChanged, self._clean_changed)):
            try:
                sig.disconnect(slot)
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
        self.write_pdf(path, indices=sorted(indices))

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
    def build_overlay(self):
        """Только наши пометки — отдельным PDF (страница на каждую страницу с пометками).
        Шрифты и содержимое исходного документа здесь не участвуют, поэтому это безопасно для любого PDF."""
        ov = pymupdf.open()
        pages = []
        from .formula import release_pdf_cache
        try:
            for i, pi in enumerate(self.pages):
                items = pi.overlay_items()
                if not items:
                    continue
                op = ov.new_page(width=pi.w, height=pi.h)
                items = sorted(items, key=lambda x: x.zValue())
                states = []
                for it in items:
                    it.bake(op)
                    states.append(it.export_state())
                pages.append({"page": i, "ov": ov.page_count - 1, "items": states})
        except Exception as e:
            ov.close()
            raise SaveFailedError(f"Не удалось сохранить пометку на странице {i + 1}: {e}") from e
        finally:
            release_pdf_cache()
        return ov, pages

    def source_bytes(self):
        """Байты документа без пометок. Если документ не меняли — исходный файл как есть."""
        if self._src_bytes is not None:
            return self._src_bytes
        return self.doc.tobytes(garbage=0)

    def build_output(self, indices=None, editable=True):
        """Готовый документ в памяти (для печати, экспорта картинок, сжатия)."""
        from .savejob import merge_mupdf
        out = pymupdf.open(stream=self.source_bytes(), filetype="pdf")
        ov, pages = self.build_overlay()
        merge_mupdf(out, ov, pages, editable=editable, subset=True)
        ov.close()
        if indices is not None:
            out.select(indices)
        try:
            meta = dict(out.metadata or {})
            meta["creator"] = f"{APP_NAME} {APP_VERSION} — {AUTHOR}"
            out.set_metadata(meta)
        except Exception:
            pass
        return out

    def write_pdf(self, path, indices=None, editable=True):
        """Защищённая запись в файл: склейка в отдельном процессе (сбой библиотеки PDF не закрывает
        программу), несколько способов по очереди, замена файла с учётом блокировок.
        Возвращает название сработавшего способа."""
        import shutil
        import tempfile
        from . import savejob
        job = Path(tempfile.mkdtemp(prefix="redcolor_save_"))
        try:
            (job / "src.pdf").write_bytes(self.source_bytes())
            ov, pages = self.build_overlay()
            if pages:
                ov.save(str(job / "ov.pdf"))
            ov.close()
            (job / "job.json").write_text(json.dumps({
                "pages": pages, "editable": editable, "indices": indices,
                "creator": f"{APP_NAME} {APP_VERSION} — {AUTHOR}"}, ensure_ascii=False), encoding="utf-8")
            result, strategy, errors = savejob.run(job)
            if result is None:
                raise SaveFailedError("\n".join(errors) or "неизвестная ошибка")
            _replace_file(result, path)
            return strategy
        finally:
            shutil.rmtree(job, ignore_errors=True)

    def save(self, path):
        strategy = self.write_pdf(path)
        self.last_save_strategy = strategy
        self.path = str(path)
        self.title = Path(path).name
        self.undo.setClean()
        self.path_changed.emit(self.path)
        return strategy

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


class SaveFailedError(Exception):
    """Ни один способ сохранения не сработал."""


def _replace_file(src, dst):
    """Записывает рядом временную копию и только затем заменяет исходный файл."""
    import shutil
    import tempfile
    import time
    dst = Path(dst)
    fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.redcolor-", suffix=".tmp", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as source:
            shutil.copyfileobj(source, out)
            out.flush()
            os.fsync(out.fileno())
        last = None
        for attempt in range(10):
            try:
                os.replace(tmp, dst)
                return
            except PermissionError as e:
                last = e
                time.sleep(0.2 + 0.15 * attempt)
        raise FileLockedError(str(dst)) from last
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
