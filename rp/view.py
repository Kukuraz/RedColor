# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Область просмотра документа: прокрутка, масштаб, инструменты мыши, вставка из буфера."""
import json
import math

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (QApplication, QFileDialog, QGraphicsPathItem, QGraphicsRectItem, QGraphicsView,
                               QMessageBox)

from . import fonts
from .config import S
from .items import BoxItem, ImageItem, InkItem, ShapeItem, SYMBOLS, TextItem, create_item, _png_bytes
from .theme import T

ITEMS_MIME = "application/x-redcolor-items"
ZOOM_STEPS = [0.1, 0.125, 0.25, 0.333, 0.5, 0.667, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0,
              4.0, 5.0, 6.4, 8.0]


def quant_zoom(z):
    """Округление масштаба рендера, чтобы переиспользовать готовые картинки."""
    step = 1.18
    return step ** math.ceil(math.log(max(z, 0.05)) / math.log(step))


class PdfView(QGraphicsView):
    zoom_changed = Signal(float)
    page_changed = Signal(int, int)
    selection_changed = Signal()
    tool_finished = Signal()
    status = Signal(str)

    def __init__(self, model, ctx, parent=None):
        super().__init__(model.scene, parent)
        self.model = model
        self.ctx = ctx                # общее состояние инструментов (MainWindow.tools)
        self.z = 1.0
        self.fit_mode = "auto"
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.DontSavePainterState)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setBackgroundBrush(QColor(T["canvas"]))
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setStyleSheet("")
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(25)
        self._render_timer.timeout.connect(self.update_render)
        self._hires_timer = QTimer(self)
        self._hires_timer.setSingleShot(True)
        self._hires_timer.setInterval(140)
        self._hires_timer.timeout.connect(lambda: self.update_render(hires=True))
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        model.layout_changed.connect(self._layout_changed)
        model.scene.selectionChanged.connect(self.selection_changed.emit)
        self._press = None
        self._temp = None
        self._move_before = None
        self._pan = None
        self._space = False
        self._last_mouse_scene = None
        self._erase = []
        self._cur_page = -1
        self.setMouseTracking(True)
        QTimer.singleShot(0, self.apply_fit)

    # ================================================================ масштаб
    def set_zoom(self, z, anchor=None):
        z = max(0.05, min(z, 16.0))
        if anchor is None:
            anchor = self.viewport().rect().center()
        scene_pt = self.mapToScene(anchor)
        self.z = z
        self.setTransform(QTransform.fromScale(z, z))
        new_pt = self.mapFromScene(scene_pt)
        d = new_pt - anchor
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
        self.zoom_changed.emit(z)
        self._render_timer.start()
        self._hires_timer.start()
        for it in self.scene().selectedItems():
            it.prepareGeometryChange()

    def zoom_step(self, direction, anchor=None):
        self.fit_mode = None
        if direction > 0:
            nz = next((s for s in ZOOM_STEPS if s > self.z * 1.01), ZOOM_STEPS[-1])
        else:
            nz = next((s for s in reversed(ZOOM_STEPS) if s < self.z * 0.99), ZOOM_STEPS[0])
        self.set_zoom(nz, anchor)

    def fit_width(self):
        self.fit_mode = "width"
        self.apply_fit()

    def fit_page(self):
        self.fit_mode = "page"
        self.apply_fit()

    def actual_size(self):
        self.fit_mode = None
        self.set_zoom(96 / 72)

    def apply_fit(self):
        if not self.model.pages:
            return
        vw = self.viewport().width() - 48
        vh = self.viewport().height() - 24
        cur = self.current_page()
        page = self.model.pages[max(cur, 0)]
        if self.fit_mode in ("width", "auto"):
            maxw = max(p.w for p in self.model.pages)
            z = max(vw, 50) / maxw
            if self.fit_mode == "auto":
                z = min(z, 96 / 72)
            self.set_zoom(z)
            self.go_to_page(cur, keep_offset=True)
        elif self.fit_mode == "page":
            self.set_zoom(min(max(vw, 50) / page.w, max(vh, 50) / page.h))
            self.go_to_page(cur)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)
        self._render_timer.start()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y()
            if d:
                self.fit_mode = None
                factor = 1.0015 ** d
                self.set_zoom(self.z * factor, e.position().toPoint())
            e.accept()
            return
        super().wheelEvent(e)

    # ================================================================ страницы
    def current_page(self):
        if not self.model.pages:
            return 0
        c = self.mapToScene(self.viewport().rect().center())
        top = self.mapToScene(0, 0).y()
        best, bi = 0, 0
        for i, p in enumerate(self.model.pages):
            r = p.sceneBoundingRect()
            vis = min(r.bottom(), self.mapToScene(0, self.viewport().height()).y()) - max(r.top(), top)
            if vis > best + 1e-6:
                best, bi = vis, i
        return bi

    def go_to_page(self, i, keep_offset=False):
        if not self.model.pages:
            return
        i = max(0, min(i, len(self.model.pages) - 1))
        p = self.model.pages[i]
        y = p.scenePos().y() - 8 / self.z
        pt = self.mapFromScene(QPointF(0, y))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + pt.y())
        self._scrolled()

    def _layout_changed(self):
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)
        self._render_timer.start()
        self._scrolled()

    def _scrolled(self, *a):
        self._render_timer.start()
        self._hires_timer.start()
        cur = self.current_page()
        if cur != self._cur_page:
            self._cur_page = cur
        self.page_changed.emit(cur, len(self.model.pages))

    def update_render(self, hires=False):
        from .render import service
        pages = self.model.pages
        if not pages:
            return
        vr = self.mapToScene(self.viewport().rect()).boundingRect()
        dpr = self.devicePixelRatioF()
        need_z = quant_zoom(self.z * dpr)
        # не рендерим гигантские картинки: ограничение по числу пикселей
        cy = vr.center().y()
        visible = []
        for i, p in enumerate(pages):
            r = p.sceneBoundingRect()
            if r.bottom() >= vr.top() - vr.height() and r.top() <= vr.bottom() + vr.height():
                visible.append((abs(r.center().y() - cy), i, p, r.intersects(vr)))
        visible.sort()
        keep = set()
        for dist, i, p, inview in visible:
            z = need_z
            maxpx = 5200 * 5200
            if p.w * p.h * z * z > maxpx:
                z = math.sqrt(maxpx / (p.w * p.h))
            z = round(z, 4)
            if p.pix is None or p.pix_zoom < z * 0.97:
                prio = (0 if inview else 10) + dist / 10000
                service().request(self.model.key, self.model.gen, i, z, prio)
            keep.add((i, z))
            if p.low is None:
                lz = 0.25
                service().request(self.model.key, self.model.gen, i, lz, 5 + dist / 10000)
                keep.add((i, lz))
        # миниатюры для ближайших страниц
        first = visible[0][1] if visible else 0
        for i in range(max(0, first - 6), min(len(pages), first + 8)):
            if pages[i].low is None:
                service().request(self.model.key, self.model.gen, i, 0.25, 50 + abs(i - first))
                keep.add((i, 0.25))
        service().cancel(self.model.key, keep)
        # освобождаем память: дальние страницы держат только миниатюру
        near = {i for _, i, _, _ in visible}
        for i, p in enumerate(pages):
            if i not in near and p.pix is not None and (i < first - 4 or i > first + 6):
                p.pix = None
                p.pix_zoom = 0.0
            elif p.pix is not None and p.pix_zoom > need_z * 2.5 and i in near:
                pass

    # ================================================================ инструменты
    def page_and_pos(self, scene_pos, strict=True):
        pi = self.model.page_at(scene_pos)
        if pi is None and not strict:
            pi = self.model.nearest_page(scene_pos)
        if pi is None:
            return None, None
        return pi, pi.mapFromScene(scene_pos)

    def text_props(self, page=None):
        return self.ctx.text_props(page)

    def _clamp_in_page(self, pi, pos):
        return QPointF(min(max(pos.x(), 0), pi.w), min(max(pos.y(), 0), pi.h))

    def editing_item(self):
        fi = self.scene().focusItem()
        if fi is not None and isinstance(fi.parentItem(), TextItem) and fi.parentItem().editing:
            return fi.parentItem()
        return None

    def mousePressEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        self._last_mouse_scene = sp
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and (self._space or self.ctx.tool == "hand")):
            self._pan = (e.position(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        tool = self.ctx.tool
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        ed = self.editing_item()
        item_under = self._item_at(e.position().toPoint())
        if ed is not None and item_under is ed:
            return super().mousePressEvent(e)
        if ed is not None:
            ed.end_edit()
        if tool == "select":
            super().mousePressEvent(e)
            self._move_before = [(it, it.state()) for it in self.scene().selectedItems() if isinstance(it, BoxItem)]
            if not self.scene().selectedItems() and item_under is None:
                self.setDragMode(QGraphicsView.RubberBandDrag)
                super().mousePressEvent(e)
            return
        pi, pos = self.page_and_pos(sp)
        if tool == "text":
            if isinstance(item_under, TextItem):
                self.scene().clearSelection()
                item_under.setSelected(True)
                item_under.start_edit(at_scene_pos=sp)
                return
            if pi is None:
                return
            self.create_text(pi, pos)
            return
        if pi is None:
            return
        if tool in ("pencil", "highlighter"):
            self._press = ("ink", pi, [(pos.x(), pos.y())])
            col = S["hl_color"] if tool == "highlighter" else self.ctx.ink_color()
            width = S["hl_width"] if tool == "highlighter" else self.ctx.ink_width()
            c = QColor(col)
            if tool == "highlighter":
                c.setAlphaF(0.4)
            it = QGraphicsPathItem(pi)
            pen = QPen(c, width, Qt.SolidLine, Qt.SquareCap if tool == "highlighter" else Qt.RoundCap, Qt.RoundJoin)
            it.setPen(pen)
            self._temp = it
            return
        if tool == "eraser":
            self._press = ("erase", pi, None)
            self._erase = []
            self._erase_at(sp)
            return
        if tool in ("ellipse", "ellipse_num", "rect", "line", "arrow") or tool in SYMBOLS:
            self._press = ("shape", pi, pos)
            r = QGraphicsRectItem(pi)
            r.setPen(QPen(QColor(T["accent"]), 1 / self.z, Qt.DashLine))
            r.setRect(QRectF(pos, pos))
            self._temp = r
            return
        if tool == "quote":
            self.ctx.place_quote(self, pi, pos)
            return
        if tool == "signature":
            self.ctx.place_signature(self, pi, pos)
            return
        if tool == "image":
            self.ctx.place_image(self, pi, pos)
            return
        if tool == "formula":
            self.ctx.place_formula(self, pi, pos)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        self._last_mouse_scene = sp
        if self._pan:
            p0, h0, v0 = self._pan
            d = e.position() - p0
            self.horizontalScrollBar().setValue(int(h0 - d.x()))
            self.verticalScrollBar().setValue(int(v0 - d.y()))
            return
        if self._press:
            kind, pi, data = self._press
            pos = self._clamp_in_page(pi, pi.mapFromScene(sp))
            if kind == "ink":
                last = data[-1]
                if math.hypot(pos.x() - last[0], pos.y() - last[1]) * self.z >= 1.2:
                    data.append((pos.x(), pos.y()))
                    path = QPainterPath(QPointF(*data[0]))
                    for x, y in data[1:]:
                        path.lineTo(x, y)
                    self._temp.setPath(path)
                return
            if kind == "erase":
                self._erase_at(sp)
                return
            if kind == "shape":
                r = QRectF(data, pos).normalized()
                if self.ctx.tool in SYMBOLS or (e.modifiers() & Qt.ShiftModifier):
                    side = max(r.width(), r.height())
                    r = QRectF(data.x() if pos.x() >= data.x() else data.x() - side,
                               data.y() if pos.y() >= data.y() else data.y() - side, side, side)
                self._temp.setRect(r)
                return
        self._update_cursor(e.position().toPoint())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan:
            self._pan = None
            self._update_cursor(e.position().toPoint())
            return
        if self._press:
            kind, pi, data = self._press
            self._press = None
            temp, self._temp = self._temp, None
            if temp is not None:
                temp.setParentItem(None)
                if temp.scene():
                    temp.scene().removeItem(temp)
            if kind == "ink":
                self._finish_ink(pi, data)
            elif kind == "erase":
                if self._erase:
                    for it in self._erase:
                        it.setVisible(True)
                    self.model.remove_items(self._erase, "Ластик")
                self._erase = []
            elif kind == "shape":
                self._finish_shape(pi, data, temp.rect() if temp else QRectF(data, data))
            return
        super().mouseReleaseEvent(e)
        if self.dragMode() == QGraphicsView.RubberBandDrag:
            self.setDragMode(QGraphicsView.NoDrag)
        if self._move_before:
            items = [it for it, _ in self._move_before]
            before = [st for _, st in self._move_before]
            after = [it.state() for it in items]
            if before != after:
                self.model.push_state(items, before, after, "Перемещение")
            self._move_before = None

    def mouseDoubleClickEvent(self, e):
        it = self._item_at(e.position().toPoint())
        if isinstance(it, TextItem) and it.editing:
            return super().mouseDoubleClickEvent(e)
        if isinstance(it, TextItem) and self.ctx.tool in ("select", "text"):
            self.scene().clearSelection()
            it.setSelected(True)
            it.start_edit(at_scene_pos=self.mapToScene(e.position().toPoint()))
            return
        super().mouseDoubleClickEvent(e)

    def _item_at(self, vpos):
        for it in self.items(vpos):
            while it is not None and not isinstance(it, BoxItem):
                it = it.parentItem()
            if isinstance(it, BoxItem):
                return it
        return None

    def _update_cursor(self, vpos):
        tool = self.ctx.tool
        if self._space or tool == "hand":
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif tool == "select":
            self.viewport().unsetCursor()
        elif tool == "text":
            self.viewport().setCursor(Qt.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.CrossCursor)

    def _erase_at(self, sp):
        r = 4 / self.z
        for it in self.scene().items(QRectF(sp.x() - r, sp.y() - r, 2 * r, 2 * r)):
            if isinstance(it, InkItem) and it.isVisible() and it not in self._erase:
                self._erase.append(it)
                it.setVisible(False)

    def _finish_ink(self, pi, pts):
        if len(pts) == 1:
            pts = [pts[0], (pts[0][0] + 0.3, pts[0][1] + 0.3)]
        hl = self.ctx.tool == "highlighter"
        it = InkItem(pts, S["hl_color"] if hl else self.ctx.ink_color(),
                     S["hl_width"] if hl else self.ctx.ink_width(), 0.4 if hl else 1.0, hl)
        self.model.add_items([(pi, it)], "Рисование")

    def _finish_shape(self, pi, start, r):
        tool = self.ctx.tool
        small = r.width() * self.z < 4 and r.height() * self.z < 4
        unit = pi.w / 595.0
        col = self.ctx.shape_color()
        width = self.ctx.shape_width()
        if tool in SYMBOLS:
            s = 14 * unit if small else max(r.width(), r.height())
            r = QRectF(start.x() - s / 2, start.y() - s / 2, s, s) if small else r
            it = ShapeItem(tool, r.width(), r.height(), col, max(width, 1.6 * unit))
        elif tool in ("line", "arrow"):
            if small:
                r = QRectF(start.x(), start.y(), 60 * unit, 0.01)
                direction = 0
            else:
                sx, sy = start.x(), start.y()
                ex = r.right() if abs(r.left() - sx) < 1e-6 else r.left()
                ey = r.bottom() if abs(r.top() - sy) < 1e-6 else r.top()
                direction = {(True, True): 0, (True, False): 1, (False, False): 2, (False, True): 3}[(ex >= sx, ey >= sy)]
            it = ShapeItem(tool, max(r.width(), 0.01), max(r.height(), 0.01), col, width, direction)
        else:
            if small:
                r = QRectF(start.x() - 40 * unit, start.y() - 16 * unit, 80 * unit, 32 * unit)
            number = None
            kind = "ellipse" if tool == "ellipse_num" else tool
            if tool == "ellipse_num":
                nums = [c.number for c in pi.overlay_items() if isinstance(c, ShapeItem) and c.number is not None]
                number = max(nums, default=0) + 1
            it = ShapeItem(kind, r.width(), r.height(), col, width, 0, number, 13 * unit)
        it.setPos(r.topLeft())
        self.model.add_items([(pi, it)], "Фигура")
        self.scene().clearSelection()
        it.setSelected(True)
        self.ctx.after_place()

    # ================================================================ текст
    def create_text(self, pi, pos, runs=None, start_edit=True, width=None, props=None):
        props = props or self.text_props(pi)
        x = pos.x()
        margin = pi.w * 0.04
        w = width or max(pi.w - x - margin, pi.w * 0.25)
        it = TextItem(props, w)
        y = pos.y() - props["size"] * 0.6 if start_edit and runs is None else pos.y()
        it.setPos(x, max(y, 0))
        it.setParentItem(pi)
        it._new = True
        if runs:
            it.set_runs(runs)
            if width is None:
                # вписываем в страницу: сначала сдвигаем влево, если не хватает — уменьшаем кегль
                full = pi.w - 2 * margin
                it.ed.setTextWidth(full)
                need = it.doc.idealWidth() + 1.0
                while need > full and it.size > 5:
                    it.set_props(size=round(it.size * full / need * 2) / 2 - 0.5)
                    it.ed.setTextWidth(full)
                    need = it.doc.idealWidth() + 1.0
                if need > w:
                    x = max(margin, pi.w - margin - need)
                    it.setPos(x, it.pos().y())
                it.fit_width(min(max(pi.w - x - margin, need), full))
                if it.pos().y() + it.size_h() > pi.h:
                    it.setPos(it.pos().x(), max(0.0, pi.h - it.size_h() - margin))
        self.scene().clearSelection()
        it.setSelected(True)
        if start_edit:
            it.start_edit()
        else:
            it._new = False
            self.model.add_items([(pi, it)], "Текст", already=True)
        return it

    def text_edit_finished(self, item, before):
        if getattr(item, "_new", False):
            item._new = False
            if item.is_empty():
                pi = item.parentItem()
                item.setParentItem(None)
                if item.scene():
                    item.scene().removeItem(item)
                return
            self.model.add_items([(item.parentItem(), item)], "Текст", already=True)
            self.ctx.after_place()
            return
        if item.is_empty():
            self.model.remove_items([item], "Удаление текста")
            return
        after = item.state()
        if before is not None and before != after:
            self.model.push_state([item], [before], [after], "Правка текста")

    def push_state(self, items, before, after, text="Изменение"):
        self.model.push_state(items, before, after, text)

    def edit_formula_in(self, item, pos):
        self.ctx.edit_formula(self, item, pos)

    # ================================================================ буфер обмена
    def selected_boxes(self):
        return [it for it in self.scene().selectedItems() if isinstance(it, BoxItem)]

    def copy(self, cut=False):
        ed = self.editing_item()
        if ed is not None:
            return self.copy_text_selection(ed, cut)
        items = self.selected_boxes()
        if not items:
            return
        data = [it.export_state() for it in items]
        md = QMimeData()
        md.setData(ITEMS_MIME, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        texts = [it.plain_text() for it in items if isinstance(it, TextItem)]
        if texts:
            md.setText("\n".join(texts))
        QGuiApplication.clipboard().setMimeData(md)
        if cut:
            self.model.remove_items(items, "Вырезать")

    def copy_text_selection(self, item, cut=False):
        runs = item.selected_runs()
        if not runs:
            return
        cur = item.ed.textCursor()
        tmp_state = {"kind": "text", "x": 0, "y": 0, "w": item._w, "h": 10, "rot": 0, **item.props(),
                     "runs": [[al, [list(r) for r in rs]] for al, rs in runs]}
        from .formula import REGISTRY
        keys = {r[1] for _, rs in runs for r in rs if r[0] == "f"}
        tmp_state["formulas"] = {k: REGISTRY[k].to_dict() for k in keys if k in REGISTRY}
        md = QMimeData()
        md.setData(ITEMS_MIME + ".runs", json.dumps(tmp_state, ensure_ascii=False).encode("utf-8"))
        md.setText(cur.selectedText().replace(" ", "\n").replace("￼", "[формула]"))
        QGuiApplication.clipboard().setMimeData(md)
        if cut:
            cur.removeSelectedText()

    def paste(self):
        from . import clipboard as cb
        md = QGuiApplication.clipboard().mimeData()
        ed = self.editing_item()
        target_pi, target_pos = self._paste_target()
        if md.hasFormat(ITEMS_MIME + ".runs"):
            d = json.loads(bytes(md.data(ITEMS_MIME + ".runs")).decode("utf-8"))
            from .formula import from_dict
            for fd in d.get("formulas", {}).values():
                from_dict(fd)
            runs = tuple((al, tuple(tuple(r) for r in rs)) for al, rs in d["runs"])
            if ed is not None:
                ed.insert_runs(runs)
            elif target_pi is not None:
                self.create_text(target_pi, target_pos, runs, start_edit=False)
            return
        if md.hasFormat(ITEMS_MIME) and ed is None:
            data = json.loads(bytes(md.data(ITEMS_MIME)).decode("utf-8"))
            pi = target_pi or (self.model.pages[self.current_page()] if self.model.pages else None)
            if pi is None:
                return
            new = []
            for d in data:
                it = create_item(d)
                if it is None:
                    continue
                it.setPos(it.pos() + QPointF(10, 10))
                new.append((pi, it))
            if new:
                self.model.add_items(new, "Вставка")
                self.scene().clearSelection()
                for _, it in new:
                    it.setSelected(True)
            return
        runs = None
        if md.hasHtml():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                runs = cb.html_to_runs(md.html(), self.ctx.text_props(target_pi)["size"])
            except Exception as ex:
                self.status.emit(f"Не удалось разобрать вставку: {ex}")
                runs = None
            finally:
                QApplication.restoreOverrideCursor()
        if runs is None and md.hasImage() and ed is None:
            img = QImage(md.imageData())
            if not img.isNull() and target_pi is not None:
                self.insert_image_data(target_pi, target_pos, _png_bytes(img), img.width(), img.height())
                return
        if runs is None and md.hasText():
            runs = cb.text_to_runs(md.text(), self.ctx.text_props(target_pi)["size"])
        if not runs:
            return
        if ed is not None:
            ed.insert_runs(runs)
        elif target_pi is not None:
            self.create_text(target_pi, target_pos, runs, start_edit=False)

    def _paste_target(self):
        sp = self._last_mouse_scene
        if sp is not None and self.viewport().rect().contains(self.mapFromScene(sp)):
            pi, pos = self.page_and_pos(sp)
            if pi is not None:
                return pi, pos
        if not self.model.pages:
            return None, None
        pi = self.model.pages[self.current_page()]
        vr = self.mapToScene(self.viewport().rect()).boundingRect()
        pos = pi.mapFromScene(vr.center())
        return pi, QPointF(min(max(pos.x() - pi.w * 0.3, pi.w * 0.05), pi.w * 0.6), min(max(pos.y(), 20), pi.h - 40))

    def insert_image_data(self, pi, pos, data, iw, ih, signature=False, tint=None, width=None):
        maxw = width or pi.w * 0.5
        sc = min(maxw / max(iw, 1), (pi.h * 0.6) / max(ih, 1), 1.0 if width is None else 1e9)
        w, h = iw * sc, ih * sc
        if width:
            w, h = width, ih * width / max(iw, 1)
        it = ImageItem(data, w, h, tint, signature)
        it.setPos(min(max(pos.x() - w / 2, 0), max(pi.w - w, 0)), min(max(pos.y() - h / 2, 0), max(pi.h - h, 0)))
        self.model.add_items([(pi, it)], "Подпись" if signature else "Изображение")
        self.scene().clearSelection()
        it.setSelected(True)
        return it

    # ================================================================ клавиатура
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat() and self.editing_item() is None:
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        items = self.selected_boxes()
        if items and self.editing_item() is None and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10.0 if e.modifiers() & Qt.ShiftModifier else 1.0
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(e.key(), 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(e.key(), 0)
            before = [it.state() for it in items]
            for it in items:
                it.moveBy(dx, dy)
            self.model.push_state(items, before, [it.state() for it in items], "Сдвиг")
            return
        if self.editing_item() is None and not items:
            if e.key() in (Qt.Key_PageDown,):
                self.go_to_page(self.current_page() + 1)
                return
            if e.key() in (Qt.Key_PageUp,):
                self.go_to_page(self.current_page() - 1)
                return
            if e.key() == Qt.Key_Home and e.modifiers() & Qt.ControlModifier:
                self.go_to_page(0)
                return
            if e.key() == Qt.Key_End and e.modifiers() & Qt.ControlModifier:
                self.go_to_page(len(self.model.pages) - 1)
                return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat() and self._space:
            self._space = False
            self._update_cursor(self.mapFromGlobal(self.cursor().pos()))
            return
        super().keyReleaseEvent(e)

    # ================================================================ перетаскивание файлов
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        sp = self.mapToScene(e.position().toPoint())
        pi, pos = self.page_and_pos(sp, strict=False)
        handled = False
        for url in md.urls():
            p = url.toLocalFile()
            low = p.lower()
            if low.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")) and pi is not None:
                img = QImage(p)
                if not img.isNull():
                    with open(p, "rb") as f:
                        data = f.read()
                    self.insert_image_data(pi, pos, data, img.width(), img.height())
                    handled = True
            elif low.endswith(".pdf"):
                self.ctx.open_paths([p])
                handled = True
        if handled:
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
