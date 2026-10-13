# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Формулы: векторные SVG (с сайта или из LaTeX), встраиваемые в текст как символы."""
import hashlib
import re
import threading

from PySide6.QtCore import QByteArray, QObject, QRectF, QSizeF
from PySide6.QtGui import QPyTextObject, QTextCharFormat, QTextFormat
from PySide6.QtSvg import QSvgRenderer

from .config import DATA_DIR

FORMULA_TYPE = QTextFormat.UserObject + 1
PROP_KEY = QTextFormat.UserProperty + 1
PROP_DISPLAY = QTextFormat.UserProperty + 2

CACHE_DIR = DATA_DIR / "formula_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class Formula:
    """Неизменяемая формула: SVG без цвета + натуральный размер (pt) + базовый кегль."""
    __slots__ = ("key", "svg", "w", "h", "src_size", "latex", "alt", "_renderers", "_pdf")

    def __init__(self, svg, w, h, src_size, latex="", alt=""):
        self.svg = svg
        self.w, self.h = w, h
        self.src_size = src_size
        self.latex = latex
        self.alt = alt
        self.key = hashlib.md5(svg.encode("utf-8") + latex.encode("utf-8")).hexdigest()
        self._renderers = {}
        self._pdf = {}

    def colored_svg(self, color):
        s = self.svg
        s = re.sub(r"fill=['\"](#000000|#000|black)['\"]", f"fill='{color}'", s)
        s = re.sub(r"stroke=['\"](#000000|#000|black)['\"]", f"stroke='{color}'", s)
        return re.sub(r"<svg\b", f"<svg fill='{color}' color='{color}'", s, count=1)

    def renderer(self, color):
        r = self._renderers.get(color)
        if r is None:
            r = QSvgRenderer(QByteArray(self.colored_svg(color).encode("utf-8")))
            self._renderers[color] = r
        return r

    def pdf_doc(self, color):
        """Одностраничный векторный PDF с формулой — для вставки в документ при сохранении."""
        import pymupdf
        d = self._pdf.get(color)
        if d is None:
            src = pymupdf.open(stream=self.colored_svg(color).encode("utf-8"), filetype="svg")
            d = pymupdf.open("pdf", src.convert_to_pdf())
            self._pdf[color] = d
        return d

    def to_dict(self):
        return {"svg": self.svg, "w": self.w, "h": self.h, "src": self.src_size,
                "latex": self.latex, "alt": self.alt}


REGISTRY = {}


def register(f):
    old = REGISTRY.get(f.key)
    if old is not None:
        return old
    REGISTRY[f.key] = f
    return f


def from_dict(d):
    return register(Formula(d["svg"], d["w"], d["h"], d["src"], d.get("latex", ""), d.get("alt", "")))


# --------------------------------------------------------------------------- SVG с сайта
_num = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def from_site_svg(svg_text, alt=""):
    """SVG из dvisvgm: размер в pt, масштаб группы (zoom) определяет базовый кегль."""
    m = re.search(r"<svg[^>]*\swidth=['\"](" + _num + r")pt['\"][^>]*\sheight=['\"](" + _num + r")pt", svg_text)
    if not m:
        m2 = re.search(r"viewBox=['\"]\s*(" + _num + r")\s+(" + _num + r")\s+(" + _num + r")\s+(" + _num + r")", svg_text)
        if not m2:
            raise ValueError("Не удалось определить размер формулы")
        w, h = float(m2.group(3)), float(m2.group(4))
    else:
        w, h = float(m.group(1)), float(m.group(2))
    zm = re.search(r"<g[^>]*transform=['\"]matrix\((" + _num + r")\s", svg_text)
    zoom = float(zm.group(1)) if zm else 1.0
    svg_text = re.sub(r"<\?xml[^>]*\?>", "", svg_text)
    svg_text = re.sub(r"<!--.*?-->", "", svg_text, flags=re.S).strip()
    return register(Formula(svg_text, w, h, 9.0 * zoom, "", alt))


def fetch_svg(url, timeout=8):
    """Скачивает SVG формулы (с кешем на диске)."""
    name = hashlib.md5(url.encode("utf-8")).hexdigest() + ".svg"
    p = CACHE_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    txt = r.content.decode("utf-8", "replace")
    if "<svg" not in txt:
        raise ValueError("По ссылке не SVG")
    p.write_text(txt, encoding="utf-8")
    return txt


# --------------------------------------------------------------------------- LaTeX → SVG
_mpl_lock = threading.Lock()
_mpl_ready = False


def _mpl():
    global _mpl_ready
    import matplotlib
    if not _mpl_ready:
        matplotlib.use("Agg")
        from matplotlib import rcParams
        rcParams["mathtext.fontset"] = "cm"
        rcParams["mathtext.fallback"] = "cm"
        _mpl_ready = True
    from matplotlib.textpath import TextPath
    return TextPath


def _path_d(path, dx, dy):
    """matplotlib Path → SVG path d (y вниз, сдвиг dx, dy)."""
    from matplotlib.path import Path
    out = []
    verts = path.vertices
    codes = path.codes
    if codes is None:
        codes = [Path.MOVETO] + [Path.LINETO] * (len(verts) - 1)
    i = 0
    n = len(verts)
    while i < n:
        c = codes[i]
        x, y = verts[i]
        if c == Path.MOVETO:
            out.append(f"M{x + dx:.3f} {dy - y:.3f}")
            i += 1
        elif c == Path.LINETO:
            out.append(f"L{x + dx:.3f} {dy - y:.3f}")
            i += 1
        elif c == Path.CURVE3:
            x2, y2 = verts[i + 1]
            out.append(f"Q{x + dx:.3f} {dy - y:.3f} {x2 + dx:.3f} {dy - y2:.3f}")
            i += 2
        elif c == Path.CURVE4:
            x2, y2 = verts[i + 1]
            x3, y3 = verts[i + 2]
            out.append(f"C{x + dx:.3f} {dy - y:.3f} {x2 + dx:.3f} {dy - y2:.3f} {x3 + dx:.3f} {dy - y3:.3f}")
            i += 3
        elif c == Path.CLOSEPOLY:
            out.append("Z")
            i += 1
        else:
            i += 1
    return "".join(out)


class _Box:
    """Отрисованный фрагмент: пути, ширина, высота над базовой линией и глубина под ней."""

    def __init__(self, parts, w, asc, desc):
        self.parts, self.w, self.asc, self.desc = parts, w, asc, desc   # parts: [(path_or_rect, dx, dy)]


def _render_line(tex, size):
    TextPath = _mpl()
    tex = tex.strip()
    if not tex:
        return _Box([], 0, size * 0.7, size * 0.2)
    s = "$" + tex + "$"
    p = TextPath((0, 0), s, size=size)
    ext = p.get_extents()
    if len(p.vertices) == 0:
        return _Box([], size * 0.3, size * 0.7, size * 0.2)
    asc = max(ext.y1, size * 0.7)
    desc = max(-ext.y0, size * 0.2)
    return _Box([(p, -min(ext.x0, 0), 0)], ext.x1 - min(ext.x0, 0), asc, desc)


def _brace_d(x, top, bottom, w):
    """Фигурная скобка { высотой bottom-top в позиции x (ширина w)."""
    mid = (top + bottom) / 2
    h = bottom - top
    t = w * 0.18
    a = x + w * 0.55
    return (f"M{a + w*0.45:.3f} {top:.3f} C{a:.3f} {top:.3f} {a:.3f} {top + h*0.08:.3f} {a:.3f} {top + h*0.2:.3f} "
            f"L{a:.3f} {mid - h*0.12:.3f} C{a:.3f} {mid - h*0.03:.3f} {x + w*0.3:.3f} {mid:.3f} {x:.3f} {mid:.3f} "
            f"C{x + w*0.3:.3f} {mid:.3f} {a:.3f} {mid + h*0.03:.3f} {a:.3f} {mid + h*0.12:.3f} "
            f"L{a:.3f} {bottom - h*0.2:.3f} C{a:.3f} {bottom - h*0.08:.3f} {a:.3f} {bottom:.3f} {a + w*0.45:.3f} {bottom:.3f} "
            f"L{a + w*0.45:.3f} {bottom - t:.3f} C{a + t:.3f} {bottom - t:.3f} {a + t:.3f} {bottom - h*0.08:.3f} {a + t:.3f} {bottom - h*0.2:.3f} "
            f"L{a + t:.3f} {mid + h*0.12:.3f} C{a + t:.3f} {mid + h*0.05:.3f} {x + w*0.45:.3f} {mid + h*0.01:.3f} {x + w*0.3:.3f} {mid:.3f} "
            f"C{x + w*0.45:.3f} {mid - h*0.01:.3f} {a + t:.3f} {mid - h*0.05:.3f} {a + t:.3f} {mid - h*0.12:.3f} "
            f"L{a + t:.3f} {top + h*0.2:.3f} C{a + t:.3f} {top + h*0.08:.3f} {a + t:.3f} {top + t:.3f} {a + w*0.45:.3f} {top + t:.3f} Z")


_ENV_RE = re.compile(r"\\begin\{(cases|aligned|align\*?|gathered|array|matrix|split|eqnarray\*?|system)\}(\{[^}]*\})?(.*?)\\end\{\1\}", re.S)


def _prep(tex):
    tex = tex.replace("\\displaystyle", "").replace("\\limits", "")
    tex = re.sub(r"\\(?:tfrac)", r"\\frac", tex)
    tex = re.sub(r"\\frac", r"\\dfrac", tex)
    tex = tex.replace("\\left.", "").replace("\\right.", "")
    tex = re.sub(r"\\text(?:rm|normal)?\{", r"\\mathrm{", tex)
    tex = tex.replace("{,}", ",")
    return tex


def render_latex(tex, size=12.0):
    """LaTeX → (svg, w, h). Поддерживает \\begin{cases}/aligned и переносы \\\\."""
    with _mpl_lock:
        tex = _prep(tex.strip())
        lines = []        # список строк; строка = список (box, x) с выравниванием по &
        m = _ENV_RE.search(tex)
        pre, post, env, rows = tex, "", None, None
        if m:
            pre, post, env = tex[:m.start()], tex[m.end():], m.group(1)
            rows = [r for r in re.split(r"\\\\", m.group(3)) if r.strip()]
        gap = size * 0.35
        parts = []
        x = 0.0
        asc = size * 0.7
        desc = size * 0.25

        def place(box, x0, base):
            for (p, dx, dy) in box.parts:
                parts.append((p, x0 + dx, base))

        if env is None:
            seg = [r for r in re.split(r"\\\\", tex)]
            boxes = [_render_line(r.replace("&", ""), size) for r in seg]
            y = 0.0
            width = max((b.w for b in boxes), default=0)
            placed = []
            for b in boxes:
                y += b.asc
                placed.append((b, y))
                y += b.desc + gap
            total_h = y - gap
            for b, base in placed:
                place(b, 0, base)
            return _to_svg(parts, [], width, total_h)
        pre_box = _render_line(pre, size) if pre.strip() else None
        post_box = _render_line(post, size) if post.strip() else None
        cols = [re.split(r"(?<!\\)&", r) for r in rows]
        ncol = max(len(c) for c in cols)
        cell = [[_render_line(c[i] if i < len(c) else "", size) for i in range(ncol)] for c in cols]
        colw = [max(cell[r][i].w for r in range(len(cell))) for i in range(ncol)]
        row_asc = [max(b.asc for b in r) for r in cell]
        row_desc = [max(b.desc for b in r) for r in cell]
        row_gap = size * 0.45
        total = sum(row_asc) + sum(row_desc) + row_gap * (len(cell) - 1)
        rects = []
        x = 0.0
        center = total / 2
        axis = size * 0.25   # математическая ось над базовой линией
        if pre_box:
            base_pre = center + axis
            place(pre_box, 0, base_pre)
            x = pre_box.w + size * 0.15
        brace_w = size * 0.45 if env in ("cases", "system") else 0
        brace_paths = []
        if brace_w:
            brace_paths.append(_brace_d(x, 0, total, brace_w))
            x += brace_w + size * 0.25
        y = 0.0
        for r, row in enumerate(cell):
            y += row_asc[r]
            cx = x
            for i, b in enumerate(row):
                place(b, cx, y)
                cx += colw[i] + (size * 0.6 if i < ncol - 1 else 0)
            y += row_desc[r] + row_gap
        x += sum(colw) + size * 0.6 * (ncol - 1)
        if post_box:
            place(post_box, x + size * 0.15, center + axis)
            x += post_box.w + size * 0.15
        top = min(0.0, center + axis - (pre_box.asc if pre_box else 0))
        bottom = max(total, center + axis + (pre_box.desc if pre_box else 0))
        return _to_svg(parts, brace_paths, x, bottom - top, -top)


def _to_svg(parts, extra_d, w, h, shift=0.0):
    pad = 0.5
    W, H = w + 2 * pad, h + 2 * pad
    body = "".join(f"<path d='{_path_d(p, dx + pad, base + pad + shift)}'/>" for p, dx, base in parts)
    if extra_d:
        body += (f"<g transform='translate({pad} {pad + shift})'>"
                 + "".join(f"<path d='{d}'/>" for d in extra_d) + "</g>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{W:.3f}pt' height='{H:.3f}pt' "
           f"viewBox='0 0 {W:.3f} {H:.3f}'>{body}</svg>")
    return svg, W, H


def from_latex(tex, size=12.0):
    svg, w, h = render_latex(tex, size)
    return register(Formula(svg, w, h, size, tex, ""))


# --------------------------------------------------------------------------- объект в тексте
class FormulaObject(QPyTextObject):
    """Рисует формулу внутри QTextDocument. Масштаб = кегль текста / базовый кегль формулы."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner           # TextItem
        self.record = None           # при сохранении: {pos: QRectF}

    def _scale(self, f):
        return self.owner.size / max(f.src_size, 1.0)

    def intrinsicSize(self, doc, pos, fmt):
        f = REGISTRY.get(fmt.property(PROP_KEY))
        if f is None:
            return QSizeF(10, 10)
        s = self._scale(f)
        return QSizeF(f.w * s, f.h * s)

    def drawObject(self, painter, rect, doc, pos, fmt):
        f = REGISTRY.get(fmt.property(PROP_KEY))
        if f is None:
            return
        if self.record is not None:
            self.record[pos] = (QRectF(rect), f.key)
            return
        f.renderer(self.owner.color).render(painter, rect)


def char_format(f, display=False):
    cf = QTextCharFormat()
    cf.setObjectType(FORMULA_TYPE)
    cf.setProperty(PROP_KEY, f.key)
    cf.setProperty(PROP_DISPLAY, bool(display))
    cf.setVerticalAlignment(QTextCharFormat.AlignNormal if display else QTextCharFormat.AlignMiddle)
    return cf
