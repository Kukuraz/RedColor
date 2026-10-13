# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Объекты на странице: текст (с формулами), изображения/подписи, рисунки от руки, фигуры и знаки.

Координаты: родитель — PageItem, 1 единица = 1 pt PDF (страница в отображаемой ориентации).
"""
import math

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QKeySequence, QPainter, QPainterPath, QPen,
                           QPicture, QPixmap, QPolygonF, QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextOption)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsTextItem

from . import fonts
from .formula import (FORMULA_TYPE, PROP_DISPLAY, PROP_KEY, REGISTRY, FormulaObject, char_format,
                      from_dict)
from .theme import T

HANDLE_PX = 7.0
OBJ = "￼"


def rgb(color):
    c = QColor(color)
    return (c.redF(), c.greenF(), c.blueF())


def _cx(line, pos):
    r = line.cursorToX(pos)
    return r[0] if isinstance(r, (tuple, list)) else r


def _frect(r):
    import pymupdf
    return pymupdf.Rect(r.left(), r.top(), r.right(), r.bottom())


# =========================================================================== базовый
class BoxItem(QGraphicsObject):
    kind = "box"
    keep_aspect = False
    handles_mode = "all"      # all | h | none
    min_w = 4.0
    min_h = 4.0

    def __init__(self, w, h):
        super().__init__()
        self._w = max(w, 1.0)
        self._h = max(h, 1.0)
        self._drag = None
        self._hover = False
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemIsFocusable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    # ---- геометрия
    def size(self):
        return self._w, self._h

    def set_size(self, w, h):
        w, h = max(w, 1.0), max(h, 1.0)
        if abs(w - self._w) < 1e-6 and abs(h - self._h) < 1e-6:
            return
        self.prepareGeometryChange()
        self._w, self._h = w, h
        self.on_resized()
        self.update()

    def on_resized(self):
        pass

    def view_scale(self):
        sc = self.scene()
        if sc and sc.views():
            return max(sc.views()[0].transform().m11(), 1e-3)
        return 1.0

    def hs(self):
        return HANDLE_PX / self.view_scale()

    def margin(self):
        return 0.0

    def boundingRect(self):
        m = self.hs() + self.margin() + 2
        extra = self.extra_rect()
        r = QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m)
        return r.united(extra) if extra is not None else r

    def extra_rect(self):
        return None

    def shape(self):
        p = QPainterPath()
        m = max(self.margin(), 3 / self.view_scale())
        p.addRect(QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m))
        if self.isSelected():
            for pt in self.handle_points().values():
                p.addRect(QRectF(pt.x() - self.hs(), pt.y() - self.hs(), 2 * self.hs(), 2 * self.hs()))
        return p

    def handle_points(self):
        w, h = self._w, self._h
        if self.handles_mode == "none":
            return {}
        if self.handles_mode == "h":
            return {"l": QPointF(0, h / 2), "r": QPointF(w, h / 2)}
        return {"tl": QPointF(0, 0), "t": QPointF(w / 2, 0), "tr": QPointF(w, 0), "r": QPointF(w, h / 2),
                "br": QPointF(w, h), "b": QPointF(w / 2, h), "bl": QPointF(0, h), "l": QPointF(0, h / 2)}

    def handle_at(self, pos):
        if not self.isSelected():
            return None
        hs = self.hs() * 1.1
        for k, pt in self.handle_points().items():
            if abs(pos.x() - pt.x()) <= hs and abs(pos.y() - pt.y()) <= hs:
                return k
        return None

    # ---- отрисовка
    def paint(self, p, opt, widget=None):
        self.paint_content(p)
        if self.isSelected():
            s = self.view_scale()
            pen = QPen(QColor(T["accent"]), 1.2 / s)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            m = self.margin() + 1.5 / s
            p.drawRect(QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m))
            hs = self.hs() * 0.55
            p.setBrush(QColor("#ffffff"))
            for pt in self.handle_points().values():
                p.drawRect(QRectF(pt.x() - hs, pt.y() - hs, 2 * hs, 2 * hs))
        elif self._hover:
            s = self.view_scale()
            pen = QPen(QColor(T["accent"]), 1.0 / s, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            m = self.margin() + 1.5 / s
            p.drawRect(QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m))

    def paint_content(self, p):
        pass

    # ---- мышь
    _CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                "bl": Qt.SizeBDiagCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}

    def hoverEnterEvent(self, e):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self._hover = False
        self.unsetCursor()
        self.update()

    def hoverMoveEvent(self, e):
        h = self.handle_at(e.pos())
        if h:
            self.setCursor(self._CURSORS[h])
        else:
            self.setCursor(Qt.SizeAllCursor if self.isSelected() else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        h = self.handle_at(e.pos()) if e.button() == Qt.LeftButton else None
        if h:
            self._drag = (h, self.pos(), self._w, self._h, self.state())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return super().mouseMoveEvent(e)
        h, p0, w0, h0, _ = self._drag
        parent = self.parentItem()
        pp = parent.mapFromScene(e.scenePos()) if parent else e.scenePos()
        a = math.radians(self.rotation())
        dx, dy = pp.x() - p0.x(), pp.y() - p0.y()
        lx = dx * math.cos(a) + dy * math.sin(a)
        ly = -dx * math.sin(a) + dy * math.cos(a)
        x0, y0, x1, y1 = 0.0, 0.0, w0, h0
        if "l" in h:
            x0 = min(lx, x1 - self.min_w)
        if "r" in h:
            x1 = max(lx, x0 + self.min_w)
        if h.startswith("t"):
            y0 = min(ly, y1 - self.min_h)
        if h.startswith("b"):
            y1 = max(ly, y0 + self.min_h)
        keep = self.keep_aspect != bool(e.modifiers() & Qt.ShiftModifier)
        if keep and len(h) == 2 and w0 > 0 and h0 > 0:
            ratio = w0 / h0
            nw, nh = x1 - x0, y1 - y0
            if nw / ratio > nh:
                nh = nw / ratio
            else:
                nw = nh * ratio
            if "l" in h:
                x0 = x1 - nw
            else:
                x1 = x0 + nw
            if h.startswith("t"):
                y0 = y1 - nh
            else:
                y1 = y0 + nh
        nx = p0.x() + x0 * math.cos(a) - y0 * math.sin(a)
        ny = p0.y() + x0 * math.sin(a) + y0 * math.cos(a)
        self.setPos(nx, ny)
        self.resize_to(x1 - x0, y1 - y0, h)
        e.accept()

    def resize_to(self, w, h, handle):
        self.set_size(w, h)

    def mouseReleaseEvent(self, e):
        if self._drag:
            before = self._drag[4]
            self._drag = None
            after = self.state()
            if before != after:
                v = self.scene().views()[0] if self.scene() and self.scene().views() else None
                if v is not None and hasattr(v, "push_state"):
                    v.push_state([self], [before], [after], "Изменение размера")
            e.accept()
            return
        super().mouseReleaseEvent(e)

    # ---- состояние
    def base_state(self):
        return {"kind": self.kind, "x": round(self.pos().x(), 3), "y": round(self.pos().y(), 3),
                "w": round(self._w, 3), "h": round(self._h, 3), "rot": round(self.rotation(), 3)}

    def state(self):
        return self.base_state()

    def apply_state(self, d):
        self.setPos(d["x"], d["y"])
        self.setRotation(d.get("rot", 0))
        self.set_size(d["w"], d["h"])

    def export_state(self):
        return self.state()

    def bake(self, page):
        pass

    # ---- общие свойства (для панели формата)
    def set_color(self, color):
        pass

    def get_color(self):
        return None


# =========================================================================== текст
class EditText(QGraphicsTextItem):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            self.owner.paste_hook()
            e.accept()
            return
        if e.matches(QKeySequence.Copy) or e.matches(QKeySequence.Cut):
            self.owner.copy_selection(cut=e.matches(QKeySequence.Cut))
            e.accept()
            return
        if e.key() == Qt.Key_Escape:
            self.owner.end_edit()
            e.accept()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() not in (Qt.PopupFocusReason, Qt.ActiveWindowFocusReason):
            self.owner.end_edit()

    def mouseDoubleClickEvent(self, e):
        pos = self.document().documentLayout().hitTest(e.pos(), Qt.FuzzyHit)
        key = self.owner.formula_at(pos)
        if key:
            self.owner.edit_formula(pos)
            e.accept()
            return
        super().mouseDoubleClickEvent(e)


class TextItem(BoxItem):
    kind = "text"
    handles_mode = "h"
    min_w = 12.0

    def __init__(self, props, w=200.0):
        super().__init__(w, 10)
        self.family = props.get("font", "Minion Pro")
        self.size = float(props.get("size", 12.0))
        self.color = props.get("color", "#ff0000")
        self.bold = bool(props.get("bold", False))
        self.italic = bool(props.get("italic", False))
        self.align = props.get("align", "left")
        self.editing = False
        self._edit_before = None
        self.ed = EditText(self)
        self.ed.setPos(0, 0)
        self.doc = self.ed.document()
        self.doc.setDocumentMargin(0)
        self.doc.setUseDesignMetrics(True)
        self.fobj = FormulaObject(self)
        self.doc.documentLayout().registerHandler(FORMULA_TYPE, self.fobj)
        self.ed.setTextInteractionFlags(Qt.NoTextInteraction)
        self.ed.setAcceptedMouseButtons(Qt.NoButton)
        self.ed.setAcceptHoverEvents(False)
        self.doc.contentsChanged.connect(self._sync)
        self.apply_format()

    # ---- формат
    def props(self):
        return {"font": self.family, "size": self.size, "color": self.color, "bold": self.bold,
                "italic": self.italic, "align": self.align}

    def apply_format(self):
        f = fonts.make_qfont(self.family, self.size, self.bold, self.italic)
        self.doc.setDefaultFont(f)
        self.ed.setDefaultTextColor(QColor(self.color))
        al = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight,
              "justify": Qt.AlignJustify}.get(self.align, Qt.AlignLeft)
        opt = QTextOption(al)
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.doc.setDefaultTextOption(opt)
        self.ed.setTextWidth(self._w)
        self.doc.markContentsDirty(0, max(self.doc.characterCount(), 1))
        self._sync()
        self.update()

    def set_props(self, **kw):
        for k, v in kw.items():
            if k == "font":
                self.family = v
            elif k in ("size", "color", "bold", "italic", "align"):
                setattr(self, k, v)
        self.apply_format()

    def set_color(self, color):
        self.set_props(color=color)

    def get_color(self):
        return self.color

    def on_resized(self):
        if abs(self.ed.textWidth() - self._w) > 1e-6:
            self.ed.setTextWidth(self._w)

    def resize_to(self, w, h, handle):
        self.set_size(w, self._h)
        self._sync()

    def _sync(self):
        h = max(self.doc.size().height(), self.size * 1.1)
        if abs(h - self._h) > 0.01:
            self.prepareGeometryChange()
            self._h = h
            self.update()

    def size_h(self):
        return self._h

    def natural_width(self):
        return self.doc.idealWidth()

    def fit_width(self, max_w):
        """Сужает рамку до текста (но не шире max_w)."""
        self.ed.setTextWidth(max_w)
        w = min(max_w, self.doc.idealWidth() + 1.0)
        self.set_size(max(w, self.min_w), self._h)
        self.ed.setTextWidth(self._w)
        self._sync()

    # ---- содержимое
    def runs(self):
        out = []
        block = self.doc.begin()
        while block.isValid():
            al = None
            if block.blockFormat().hasProperty(QTextBlockFormat.BlockAlignment):
                a = block.blockFormat().alignment()
                al = "center" if a & Qt.AlignHCenter else "right" if a & Qt.AlignRight else None
            runs = []
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    if cf.objectType() == FORMULA_TYPE:
                        for _ in frag.text():
                            runs.append(("f", cf.property(PROP_KEY), bool(cf.property(PROP_DISPLAY))))
                    else:
                        t = frag.text()
                        if runs and runs[-1][0] == "t":
                            runs[-1] = ("t", runs[-1][1] + t)
                        else:
                            runs.append(("t", t))
                it += 1
            out.append((al, tuple(runs)))
            block = block.next()
        return tuple(out)

    def set_runs(self, blocks):
        self.doc.blockSignals(True)
        self.doc.clear()
        cur = QTextCursor(self.doc)
        for i, (al, runs) in enumerate(blocks):
            bf = QTextBlockFormat()
            if al:
                bf.setAlignment(Qt.AlignHCenter if al == "center" else Qt.AlignRight)
            if i == 0:
                cur.setBlockFormat(bf)
            else:
                cur.insertBlock(bf, QTextCharFormat())
            for r in runs:
                if r[0] == "t":
                    cur.insertText(r[1], QTextCharFormat())
                elif r[1] in REGISTRY:
                    cur.insertText(OBJ, char_format(REGISTRY[r[1]], r[2]))
        self.doc.blockSignals(False)
        self.ed.setTextWidth(self._w)
        self._sync()
        self.update()

    def plain_text(self):
        parts = []
        for al, runs in self.runs():
            s = ""
            for r in runs:
                if r[0] == "t":
                    s += r[1]
                else:
                    f = REGISTRY.get(r[1])
                    s += (f" ${f.latex}$ " if f and f.latex else (f.alt.strip() if f and f.alt else " [формула] "))
            parts.append(s)
        return "\n".join(parts)

    def is_empty(self):
        return all(not runs or all(r[0] == "t" and not r[1].strip() for r in runs) for _, runs in self.runs())

    def insert_runs(self, blocks, cursor=None):
        """Вставка блоков (с формулами) в позицию курсора."""
        cur = cursor or self.ed.textCursor()
        cur.beginEditBlock()
        for i, (al, runs) in enumerate(blocks):
            if i > 0:
                bf = QTextBlockFormat()
                if al:
                    bf.setAlignment(Qt.AlignHCenter if al == "center" else Qt.AlignRight)
                cur.insertBlock(bf, QTextCharFormat())
            elif al and cur.block().text().strip() == "":
                bf = QTextBlockFormat()
                bf.setAlignment(Qt.AlignHCenter if al == "center" else Qt.AlignRight)
                cur.setBlockFormat(bf)
            for r in runs:
                if r[0] == "t":
                    cur.insertText(r[1], QTextCharFormat())
                elif r[1] in REGISTRY:
                    cur.insertText(OBJ, char_format(REGISTRY[r[1]], r[2]))
        cur.endEditBlock()
        self.ed.setTextCursor(cur)

    def formula_at(self, pos):
        if pos < 0:
            return None
        for p in (pos, pos - 1):
            if p < 0:
                continue
            c = QTextCursor(self.doc)
            c.setPosition(p)
            c.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            cf = c.charFormat()
            if c.selectedText() == OBJ and cf.objectType() == FORMULA_TYPE:
                return cf.property(PROP_KEY)
        return None

    def edit_formula(self, pos):
        v = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if v is not None and hasattr(v, "edit_formula_in"):
            v.edit_formula_in(self, pos)

    def replace_formula(self, pos, f):
        for p in (pos, pos - 1):
            if p < 0:
                continue
            c = QTextCursor(self.doc)
            c.setPosition(p)
            c.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            if c.selectedText() == OBJ and c.charFormat().objectType() == FORMULA_TYPE:
                disp = bool(c.charFormat().property(PROP_DISPLAY))
                c.insertText(OBJ, char_format(f, disp))
                return True
        return False

    # ---- редактирование
    def start_edit(self, select_all=False, at_scene_pos=None):
        if self.editing:
            return
        self.editing = True
        self._edit_before = self.state()
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.ed.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.ed.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.ed.setFocus(Qt.MouseFocusReason)
        cur = self.ed.textCursor()
        if select_all:
            cur.select(QTextCursor.Document)
        elif at_scene_pos is not None:
            p = self.ed.mapFromScene(at_scene_pos)
            pos = self.doc.documentLayout().hitTest(p, Qt.FuzzyHit)
            cur.setPosition(max(pos, 0))
        else:
            cur.movePosition(QTextCursor.End)
        self.ed.setTextCursor(cur)
        self.update()

    def end_edit(self):
        if not self.editing:
            return
        self.editing = False
        cur = self.ed.textCursor()
        cur.clearSelection()
        self.ed.setTextCursor(cur)
        self.ed.setTextInteractionFlags(Qt.NoTextInteraction)
        self.ed.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.ed.clearFocus()
        before, self._edit_before = self._edit_before, None
        v = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if v is not None and hasattr(v, "text_edit_finished"):
            v.text_edit_finished(self, before)

    def paste_hook(self):
        v = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if v is not None and hasattr(v, "paste"):
            v.paste()

    def copy_selection(self, cut=False):
        v = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if v is not None and hasattr(v, "copy_text_selection"):
            v.copy_text_selection(self, cut)

    def selected_runs(self):
        cur = self.ed.textCursor()
        if not cur.hasSelection():
            return None
        a, b = cur.selectionStart(), cur.selectionEnd()
        out = []
        block = self.doc.findBlock(a)
        while block.isValid() and block.position() <= b:
            runs = []
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fs, fe = frag.position(), frag.position() + frag.length()
                    s, e = max(fs, a), min(fe, b)
                    if s < e:
                        cf = frag.charFormat()
                        t = frag.text()[s - fs:e - fs]
                        if cf.objectType() == FORMULA_TYPE:
                            for _ in t:
                                runs.append(("f", cf.property(PROP_KEY), bool(cf.property(PROP_DISPLAY))))
                        else:
                            runs.append(("t", t))
                it += 1
            out.append((None, tuple(runs)))
            block = block.next()
        return tuple(out)

    # ---- состояние
    def state(self):
        d = self.base_state()
        d.update(self.props())
        d["runs"] = self.runs()
        return d

    def export_state(self):
        d = self.state()
        keys = {r[1] for _, runs in d["runs"] for r in runs if r[0] == "f"}
        d["formulas"] = {k: REGISTRY[k].to_dict() for k in keys if k in REGISTRY}
        d["runs"] = [[al, [list(r) for r in runs]] for al, runs in d["runs"]]
        return d

    def apply_state(self, d):
        self.family = d.get("font", self.family)
        self.size = d.get("size", self.size)
        self.color = d.get("color", self.color)
        self.bold = d.get("bold", self.bold)
        self.italic = d.get("italic", self.italic)
        self.align = d.get("align", self.align)
        self.setPos(d["x"], d["y"])
        self.setRotation(d.get("rot", 0))
        self.prepareGeometryChange()
        self._w = d["w"]
        self.apply_format()
        if "runs" in d and d["runs"] != self.runs():
            self.set_runs(d["runs"])

    def paint_content(self, p):
        if self.editing:
            s = self.view_scale()
            p.setPen(QPen(QColor(T["accent"]), 1.0 / s))
            p.setBrush(Qt.NoBrush)
            m = 2.0 / s
            p.drawRect(QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m))

    def paint(self, p, opt, widget=None):
        if self.editing:
            self.paint_content(p)
            return
        super().paint(p, opt, widget)

    # ---- запись в PDF
    def bake(self, page):
        ffile = fonts.file_for(self.family, self.bold, self.italic)
        fname = fonts.pdf_name(ffile) if ffile else "helv"
        col = rgb(self.color)
        rot = int(round(self.rotation())) % 360
        pdf_rot = (360 - rot) % 360 if rot % 90 == 0 else 0
        # позиции формул снимаем «пробной» отрисовкой
        rec = {}
        self.fobj.record = rec
        pic = QPicture()
        pp = QPainter(pic)
        self.doc.drawContents(pp)
        pp.end()
        self.fobj.record = None
        block = self.doc.begin()
        while block.isValid():
            layout = block.layout()
            bpos = layout.position()
            text = block.text()
            for li in range(layout.lineCount()):
                line = layout.lineAt(li)
                start = line.textStart()
                end = start + line.textLength()
                base_y = bpos.y() + line.y() + line.ascent()
                seg_start = start
                for j in range(start, end + 1):
                    if j == end or text[j] == OBJ:
                        if j > seg_start:
                            seg = text[seg_start:j].replace(" ", "").replace("\t", "    ")
                            if j == end:
                                seg = seg.rstrip()
                            if seg.strip():
                                x = bpos.x() + _cx(line, seg_start)
                                pt = self.mapToParent(QPointF(x, base_y))
                                kw = dict(fontsize=self.size, color=col, rotate=pdf_rot)
                                if ffile:
                                    kw.update(fontname=fname, fontfile=ffile)
                                else:
                                    kw.update(fontname="helv")
                                page.insert_text((pt.x(), pt.y()), seg, **kw)
                        seg_start = j + 1
            block = block.next()
        for pos, (r, key) in rec.items():
            f = REGISTRY.get(key)
            if f is None:
                continue
            fr = self.mapRectToParent(r)
            page.show_pdf_page(_frect(fr), f.pdf_doc(self.color), 0, keep_proportion=False,
                               rotate=-rot if rot % 90 == 0 else 0)


# =========================================================================== картинка / подпись
def _png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


class ImageItem(BoxItem):
    kind = "image"
    keep_aspect = True

    def __init__(self, data, w, h, tint=None, signature=False):
        super().__init__(w, h)
        self.data = bytes(data)
        self.tint = tint
        self.signature = signature
        self._img = None
        self._pix = None

    def image(self):
        if self._img is None:
            img = QImage.fromData(self.data)
            if img.isNull():
                img = QImage(10, 10, QImage.Format_ARGB32)
                img.fill(Qt.transparent)
            self._img = img
        return self._img

    def pixmap(self):
        if self._pix is None:
            img = self.image()
            if max(img.width(), img.height()) > 2400:
                img = img.scaled(2400, 2400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if self.tint:
                img = tinted(img, self.tint)
            self._pix = QPixmap.fromImage(img)
        return self._pix

    def set_color(self, color):
        if self.signature:
            self.tint = color
            self._pix = None
            self.update()

    def get_color(self):
        return self.tint if self.signature else None

    def paint_content(self, p):
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pix = self.pixmap()
        p.drawPixmap(QRectF(0, 0, self._w, self._h), pix, QRectF(pix.rect()))

    def state(self):
        d = self.base_state()
        d.update(tint=self.tint, signature=self.signature, data_id=id(self.data))
        return d

    def export_state(self):
        import base64
        d = self.state()
        d["data"] = base64.b64encode(self.data).decode("ascii")
        return d

    def apply_state(self, d):
        if d.get("tint") != self.tint:
            self.tint = d.get("tint")
            self._pix = None
        super().apply_state(d)

    def bake(self, page):
        data = self.data
        if self.tint:
            data = _png_bytes(tinted(self.image(), self.tint))
        rot = int(round(self.rotation())) % 360
        r = self.mapRectToParent(QRectF(0, 0, self._w, self._h))
        page.insert_image(_frect(r), stream=data, keep_proportion=False,
                          rotate=(360 - rot) % 360 if rot % 90 == 0 else 0)


def tinted(img, color):
    out = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


# =========================================================================== рисунок от руки
class InkItem(BoxItem):
    kind = "ink"
    min_w = 1.0
    min_h = 1.0

    def __init__(self, pts, color, width, opacity=1.0, highlight=False):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, y0 = min(xs), min(ys)
        w, h = max(max(xs) - x0, 1.0), max(max(ys) - y0, 1.0)
        super().__init__(w, h)
        self.base = (w, h)
        self.pts = [(x - x0, y - y0) for x, y in pts]
        self.color = color
        self.width = width
        self.opacity = opacity
        self.highlight = highlight
        self.setPos(x0, y0)

    def margin(self):
        return self.width / 2 + 1

    def local_pts(self):
        sx = self._w / self.base[0]
        sy = self._h / self.base[1]
        return [QPointF(x * sx, y * sy) for x, y in self.pts]

    def path(self):
        pts = self.local_pts()
        path = QPainterPath()
        if not pts:
            return path
        path.moveTo(pts[0])
        if len(pts) == 1:
            path.lineTo(pts[0] + QPointF(0.01, 0.01))
        for i in range(1, len(pts) - 1):
            mid = (pts[i] + pts[i + 1]) / 2
            path.quadTo(pts[i], mid)
        if len(pts) > 1:
            path.lineTo(pts[-1])
        return path

    def paint_content(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        if self.highlight:
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        cap = Qt.SquareCap if self.highlight else Qt.RoundCap
        p.setPen(QPen(c, self.width, Qt.SolidLine, cap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def shape(self):
        if self.isSelected():
            return super().shape()
        from PySide6.QtGui import QPainterPathStroker
        st = QPainterPathStroker()
        st.setWidth(max(self.width, 6 / self.view_scale()))
        return st.createStroke(self.path())

    def set_color(self, color):
        self.color = color
        self.update()

    def get_color(self):
        return self.color

    def state(self):
        d = self.base_state()
        d.update(color=self.color, width=self.width, opacity=self.opacity, highlight=self.highlight,
                 pts=[list(p) for p in self.pts], base=list(self.base))
        return d

    def apply_state(self, d):
        self.color = d.get("color", self.color)
        self.width = d.get("width", self.width)
        self.opacity = d.get("opacity", self.opacity)
        super().apply_state(d)

    def bake(self, page):
        path = self.path()
        pts = []
        # гладкая линия: дискретизируем путь
        n = max(int(path.length() / 0.8), 2)
        for i in range(n + 1):
            pt = self.mapToParent(path.pointAtPercent(i / n))
            pts.append((pt.x(), pt.y()))
        sh = page.new_shape()
        sh.draw_polyline(pts)
        sh.finish(color=rgb(self.color), width=self.width, closePath=False, lineCap=2 if self.highlight else 1,
                  lineJoin=1, stroke_opacity=self.opacity, fill=None)
        sh.commit()


# =========================================================================== фигуры и знаки
SYMBOLS = ("check", "cross", "plus", "minus", "dot")


class ShapeItem(BoxItem):
    kind = "shape"
    min_w = 2.0
    min_h = 2.0

    def __init__(self, shape, w, h, color, width, direction=0, number=None, num_size=12.0):
        super().__init__(w, h)
        self.shape_kind = shape
        self.color = color
        self.width = width
        self.direction = direction     # для линии/стрелки: 0 ↘, 1 ↗, 2 ↖, 3 ↙
        self.number = number
        self.num_size = num_size
        self.keep_aspect = shape in SYMBOLS

    def margin(self):
        extra = self.width * 4 if self.shape_kind == "arrow" else 0
        return self.width / 2 + 1 + extra

    def extra_rect(self):
        if self.number is None:
            return None
        return QRectF(self._w - 2, -self.num_size * 1.1, self.num_size * 2.2, self.num_size * 1.3)

    def endpoints(self):
        w, h = self._w, self._h
        return [(QPointF(0, 0), QPointF(w, h)), (QPointF(0, h), QPointF(w, 0)),
                (QPointF(w, h), QPointF(0, 0)), (QPointF(w, 0), QPointF(0, h))][self.direction % 4]

    def _geom(self):
        """Список примитивов в локальных координатах: ('ellipse'|'rect', QRectF) / ('poly', [QPointF])."""
        w, h, k = self._w, self._h, self.shape_kind
        if k == "ellipse":
            return [("ellipse", QRectF(0, 0, w, h))]
        if k == "rect":
            return [("rect", QRectF(0, 0, w, h))]
        if k in ("line", "arrow"):
            a, b = self.endpoints()
            out = [("poly", [a, b])]
            if k == "arrow":
                ang = math.atan2(b.y() - a.y(), b.x() - a.x())
                L = max(6.0, self.width * 4.5)
                p1 = QPointF(b.x() - L * math.cos(ang - 0.45), b.y() - L * math.sin(ang - 0.45))
                p2 = QPointF(b.x() - L * math.cos(ang + 0.45), b.y() - L * math.sin(ang + 0.45))
                out.append(("poly", [p1, b, p2]))
            return out
        if k == "check":
            return [("poly", [QPointF(0.05 * w, 0.55 * h), QPointF(0.38 * w, 0.9 * h), QPointF(0.95 * w, 0.08 * h)])]
        if k == "cross":
            return [("poly", [QPointF(0.1 * w, 0.1 * h), QPointF(0.9 * w, 0.9 * h)]),
                    ("poly", [QPointF(0.9 * w, 0.1 * h), QPointF(0.1 * w, 0.9 * h)])]
        if k == "plus":
            return [("poly", [QPointF(0.5 * w, 0.05 * h), QPointF(0.5 * w, 0.95 * h)]),
                    ("poly", [QPointF(0.05 * w, 0.5 * h), QPointF(0.95 * w, 0.5 * h)])]
        if k == "minus":
            return [("poly", [QPointF(0.05 * w, 0.5 * h), QPointF(0.95 * w, 0.5 * h)])]
        if k == "dot":
            return [("dot", QRectF(0.2 * w, 0.2 * h, 0.6 * w, 0.6 * h))]
        return []

    def paint_content(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(self.color), self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for kind, g in self._geom():
            if kind == "ellipse":
                p.drawEllipse(g)
            elif kind == "rect":
                p.drawRect(g)
            elif kind == "poly":
                p.drawPolyline(QPolygonF(g))
            elif kind == "dot":
                p.setBrush(QColor(self.color))
                p.drawEllipse(g)
                p.setBrush(Qt.NoBrush)
        if self.number is not None:
            f = fonts.make_qfont("Arial", self.num_size, True)
            p.setFont(f)
            p.drawText(QPointF(self._w + 1, 0), str(self.number))

    def shape(self):
        if self.isSelected() or self.shape_kind in SYMBOLS or self.shape_kind == "dot":
            return super().shape()
        from PySide6.QtGui import QPainterPathStroker
        path = QPainterPath()
        for kind, g in self._geom():
            if kind == "ellipse":
                path.addEllipse(g)
            elif kind == "rect":
                path.addRect(g)
            elif kind == "poly":
                path.addPolygon(QPolygonF(g))
        st = QPainterPathStroker()
        st.setWidth(max(self.width, 8 / self.view_scale()))
        out = st.createStroke(path)
        if self.number is not None:
            out.addRect(self.extra_rect())
        return out

    def set_color(self, color):
        self.color = color
        self.update()

    def get_color(self):
        return self.color

    def state(self):
        d = self.base_state()
        d.update(shape=self.shape_kind, color=self.color, width=self.width, direction=self.direction,
                 number=self.number, num_size=self.num_size)
        return d

    def apply_state(self, d):
        self.color = d.get("color", self.color)
        self.width = d.get("width", self.width)
        self.number = d.get("number", self.number)
        self.direction = d.get("direction", self.direction)
        self.prepareGeometryChange()
        super().apply_state(d)

    def bake(self, page):
        col = rgb(self.color)
        sh = page.new_shape()
        for kind, g in self._geom():
            if kind in ("ellipse", "rect", "dot"):
                r = _frect(self.mapRectToParent(g))
                if kind == "rect":
                    sh.draw_rect(r)
                else:
                    sh.draw_oval(r)
                sh.finish(color=col, width=self.width, fill=col if kind == "dot" else None, closePath=True)
            else:
                pts = [self.mapToParent(q) for q in g]
                sh.draw_polyline([(q.x(), q.y()) for q in pts])
                sh.finish(color=col, width=self.width, closePath=False, lineCap=1, lineJoin=1)
        sh.commit()
        if self.number is not None:
            ff = fonts.file_for("Arial", True)
            pt = self.mapToParent(QPointF(self._w + 1, 0))
            kw = dict(fontsize=self.num_size, color=col)
            if ff:
                kw.update(fontname=fonts.pdf_name(ff), fontfile=ff)
            page.insert_text((pt.x(), pt.y()), str(self.number), **kw)


# =========================================================================== фабрика
def create_item(d, default_props=None):
    k = d.get("kind")
    if k == "text":
        for key, fd in (d.get("formulas") or {}).items():
            from_dict(fd)
        it = TextItem({"font": d.get("font"), "size": d.get("size", 12), "color": d.get("color", "#ff0000"),
                       "bold": d.get("bold"), "italic": d.get("italic"), "align": d.get("align", "left")},
                      d.get("w", 200))
        runs = tuple((al, tuple(tuple(r) for r in rs)) for al, rs in d.get("runs", ()))
        it.set_runs(runs)
        it.setPos(d["x"], d["y"])
        it.setRotation(d.get("rot", 0))
        return it
    if k == "image":
        import base64
        data = base64.b64decode(d["data"]) if "data" in d else b""
        it = ImageItem(data, d["w"], d["h"], d.get("tint"), d.get("signature", False))
    elif k == "ink":
        it = InkItem([(0, 0), (1, 1)], d["color"], d["width"], d.get("opacity", 1.0), d.get("highlight", False))
        it.pts = [tuple(p) for p in d["pts"]]
        it.base = tuple(d["base"])
    elif k == "shape":
        it = ShapeItem(d["shape"], d["w"], d["h"], d["color"], d["width"], d.get("direction", 0),
                       d.get("number"), d.get("num_size", 12))
    else:
        return None
    it.apply_state(d)
    return it
