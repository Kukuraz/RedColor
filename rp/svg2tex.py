# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Восстановление LaTeX из SVG-формулы (вывод dvisvgm): по глифам шрифтов TeX и их положению.

Работает эвристически: дроби, корни, индексы/степени, векторы (\\vec), системы (cases), кириллица (\\text).
Результат можно поправить в редакторе формулы.
"""
import re
import statistics
from xml.etree import ElementTree as ET

NS = {"s": "http://www.w3.org/2000/svg", "x": "http://www.w3.org/1999/xlink"}

GREEK_MI = {11: r"\alpha", 12: r"\beta", 13: r"\gamma", 14: r"\delta", 15: r"\epsilon", 16: r"\zeta", 17: r"\eta",
            18: r"\theta", 19: r"\iota", 20: r"\kappa", 21: r"\lambda", 22: r"\mu", 23: r"\nu", 24: r"\xi",
            25: r"\pi", 26: r"\rho", 27: r"\sigma", 28: r"\tau", 29: r"\upsilon", 30: r"\phi", 31: r"\chi",
            32: r"\psi", 33: r"\omega", 34: r"\varepsilon", 35: r"\vartheta", 36: r"\varpi", 37: r"\varrho",
            38: r"\varsigma", 39: r"\varphi", 58: ".", 59: ",", 60: "<", 61: "/", 62: ">", 64: r"\partial",
            96: r"\ell"}
GREEK_RM = {0: r"\Gamma", 1: r"\Delta", 2: r"\Theta", 3: r"\Lambda", 4: r"\Xi", 5: r"\Pi", 6: r"\Sigma",
            7: r"\Upsilon", 8: r"\Phi", 9: r"\Psi", 10: r"\Omega"}
SY = {0: "-", 1: r"\cdot", 2: r"\times", 3: "*", 4: r"\div", 6: r"\pm", 7: r"\mp", 14: r"\circ", 15: r"\bullet",
      17: r"\equiv", 20: r"\leq", 21: r"\geq", 24: r"\sim", 25: r"\approx", 32: r"\leftarrow", 33: r"\rightarrow",
      34: r"\uparrow", 35: r"\downarrow", 36: r"\leftrightarrow", 41: r"\Rightarrow", 44: r"\Leftrightarrow",
      47: r"\propto", 48: "'", 49: r"\infty", 50: r"\in", 54: r"\neq", 59: r"\emptyset", 62: r"\top", 63: r"\perp",
      102: r"\{", 103: r"\}", 104: r"\langle", 105: r"\rangle", 106: "|", 107: r"\|", 110: r"\backslash",
      112: "SQRT", 114: r"\nabla", 120: r"\S"}
EX_DELIM = {0: "(", 1: ")", 2: "[", 3: "]", 8: r"\{", 9: r"\}", 12: "|", 16: "(", 17: ")", 18: "(", 19: ")",
            20: "[", 21: "]", 26: r"\{", 27: r"\}", 32: "(", 33: ")", 34: "[", 35: "]", 40: r"\{", 41: r"\}",
            48: "(", 49: ")", 50: "[", 51: "]", 56: "BRACE", 58: "BRACE", 60: "BRACE", 62: "BRACE",
            80: r"\sum", 88: r"\sum", 82: r"\int", 90: r"\int", 112: "SQRT", 113: "SQRT", 114: "SQRT",
            115: "SQRT", 116: "SQRT"}

NON_GREEK_SY = {0, 1, 2, 3, 4, 6, 7, 14, 15, 17, 32, 33, 34, 35, 36, 41, 44, 47, 48, 49, 50, 54, 59, 62, 63,
                102, 103, 104, 105, 106, 107, 110, 112, 114, 120}
REF_H = {}
for c in "0123456789":
    REF_H[c] = 0.644
for c in "ABCDEFGHIJKLMNOPRSTUVWXYZ":
    REF_H[c] = 0.683
for c in "acemnorsuvwxz":
    REF_H[c] = 0.431
for c in "bdhklt":
    REF_H[c] = 0.694


# ------------------------------------------------------------------ разбор путей
_tok = re.compile(r"[MLHVCSQTAZmlhvcsqtaz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")


def path_points(d):
    pts = []
    cmd = None
    x = y = 0.0
    toks = _tok.findall(d)
    i = 0
    nums = []

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                continue
        if i >= len(toks) or (toks[i].isalpha() and cmd not in "Zz"):
            continue
        try:
            if cmd in "ML":
                x, y = num(), num()
            elif cmd in "ml":
                x, y = x + num(), y + num()
            elif cmd == "H":
                x = num()
            elif cmd == "h":
                x += num()
            elif cmd == "V":
                y = num()
            elif cmd == "v":
                y += num()
            elif cmd == "C":
                for _ in range(2):
                    pts.append((num(), num()))
                x, y = num(), num()
            elif cmd == "c":
                for _ in range(2):
                    pts.append((x + num(), y + num()))
                x, y = x + num(), y + num()
            elif cmd in "SQ":
                pts.append((num(), num()))
                x, y = num(), num()
            elif cmd in "sq":
                pts.append((x + num(), y + num()))
                x, y = x + num(), y + num()
            elif cmd == "T":
                x, y = num(), num()
            elif cmd == "t":
                x, y = x + num(), y + num()
            else:
                i += 1
                continue
        except (IndexError, ValueError):
            break
        pts.append((x, y))
    return pts


class Glyph:
    __slots__ = ("font", "code", "x0", "y0", "x1", "y1", "base", "slant")

    def __init__(self, font, code, pts):
        self.font, self.code = font, code
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
            h = self.y1 - self.y0
            if h > 0.5:
                top = [p[0] for p in pts if p[1] < self.y0 + h * 0.3]
                bot = [p[0] for p in pts if p[1] > self.y1 - h * 0.3]
                self.slant = ((sum(top) / len(top)) - (sum(bot) / len(bot))) / h if top and bot else 0.0
            else:
                self.slant = 0.0
        else:
            self.x0 = self.x1 = self.y0 = self.y1 = 0.0
            self.slant = 0.0


class El:
    """Элемент разметки: латех-строка + габариты (y вниз) + базовая линия + кегль."""
    __slots__ = ("tex", "x0", "y0", "x1", "y1", "base", "size", "kind", "font", "code")

    def __init__(self, tex, x0, y0, x1, y1, base, size, kind="sym", font=None, code=None):
        self.tex, self.x0, self.y0, self.x1, self.y1 = tex, x0, y0, x1, y1
        self.base, self.size, self.kind, self.font, self.code = base, size, kind, font, code

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


# ------------------------------------------------------------------ определение шрифтов
def classify_fonts(glyphs, uses):
    by_font = {}
    for f, c in uses:
        by_font.setdefault(f, set()).add(c)
    kinds = {}
    for f, codes in by_font.items():
        gl = [glyphs[(f, c)] for c in codes if (f, c) in glyphs]
        hs = [g.y1 - g.y0 for g in gl if g.y1 > g.y0]
        if any(c >= 192 for c in codes) or any(128 <= c < 192 for c in codes) and not any(c in (112, 113) for c in codes):
            kinds[f] = "cyr"
            continue
        letters = [g for g in gl if 65 <= g.code <= 90 or 97 <= g.code <= 122 or 11 <= g.code <= 39]
        slants = [g.slant for g in letters if g.y1 - g.y0 > 0.5]
        slant = statistics.median(slants) if slants else 0.0
        has_greek = any(11 <= c <= 39 for c in codes)
        has_digits = any(48 <= c <= 57 for c in codes)
        has_ops = any(c in (40, 41, 43, 61) for c in codes)
        tall = statistics.median(hs) if hs else 0
        ascii_letters = any(65 <= c <= 90 or 97 <= c <= 122 for c in codes)
        sy_like = codes <= set(SY) and not ascii_letters and not has_digits
        if sy_like:
            non_greek = codes & NON_GREEK_SY
            wide = [g for g in gl if g.y1 > g.y0 and (g.x1 - g.x0) / (g.y1 - g.y0) > 1.55]
            if non_greek or wide:
                kinds[f] = "sy"
                continue
        if codes <= set(EX_DELIM) and tall > 0 and any(c >= 16 for c in codes) and not has_digits:
            kinds[f] = "ex"
        elif has_greek and slant > 0.06:
            kinds[f] = "mi"
        elif slants and slant > 0.08:
            kinds[f] = "mi"
        elif has_digits or has_ops:
            kinds[f] = "rm"
        elif letters and slant <= 0.08 and slants:
            kinds[f] = "rm"
        else:
            kinds[f] = "mi"
    # уточнение для «ex»: крупные скобки/корни
    for f, codes in by_font.items():
        if kinds.get(f) == "sy" and any(c in (56, 58, 60, 62) for c in codes):
            kinds[f] = "ex"
    return kinds


T2A_UP = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
T2A_LO = "абвгдежзийклмнопрстуфхцчшщъыьэюя"


def char_for(kind, code):
    if kind == "cyr":
        if 192 <= code <= 223:
            return T2A_UP[code - 192], "cyr"
        if 224 <= code <= 255:
            return T2A_LO[code - 224], "cyr"
        if code == 156:
            return "Ё", "cyr"
        if code == 188:
            return "ё", "cyr"
        if 32 <= code < 127:
            return chr(code), "cyrtext"
        return "?", "cyr"
    if kind == "mi":
        if code in GREEK_MI:
            return GREEK_MI[code], "sym"
        if code == 126:
            return "VEC", "accent"
        if 65 <= code <= 90 or 97 <= code <= 122 or 48 <= code <= 57:
            return chr(code), "sym"
        return chr(code) if 32 < code < 127 else "?", "sym"
    if kind == "rm":
        if code in GREEK_RM:
            return GREEK_RM[code], "sym"
        if code == 126:
            return "TILDE", "accent"
        if code == 94:
            return "HAT", "accent"
        if code == 123:
            return "-", "sym"
        if 32 < code < 127:
            ch = chr(code)
            return ("\\{" if ch == "{" else "\\}" if ch == "}" else ch), "rmchar"
        return "?", "sym"
    if kind == "sy":
        t = SY.get(code, "?")
        if t == "SQRT":
            return t, "sqrt"
        return t, "sym"
    if kind == "ex":
        t = EX_DELIM.get(code, "?")
        if t == "SQRT":
            return t, "sqrt"
        if t == "BRACE":
            return t, "brace"
        return t, "delim"
    return "?", "sym"


# ------------------------------------------------------------------ сборка
def svg_to_latex(svg_text):
    root = ET.fromstring(svg_text)
    glyph_paths = {}
    for p in root.iter("{http://www.w3.org/2000/svg}path"):
        pid = p.get("id")
        if pid:
            glyph_paths[pid] = p.get("d") or ""
    glyphs = {}
    for pid, d in glyph_paths.items():
        m = re.match(r"g(\d+)-(\d+)$", pid)
        if m:
            f, c = int(m.group(1)), int(m.group(2))
            glyphs[(f, c)] = Glyph(f, c, path_points(d))
    uses = []
    for u in root.iter("{http://www.w3.org/2000/svg}use"):
        href = u.get("{http://www.w3.org/1999/xlink}href") or u.get("href") or ""
        m = re.match(r"#g(\d+)-(\d+)$", href)
        if not m:
            continue
        uses.append((int(m.group(1)), int(m.group(2)), float(u.get("x", 0)), float(u.get("y", 0))))
    rects = []
    for r in root.iter("{http://www.w3.org/2000/svg}rect"):
        x, y = float(r.get("x", 0)), float(r.get("y", 0))
        w, h = float(r.get("width", 0)), float(r.get("height", 0))
        rects.append((x, y, x + w, y + h))
    if not uses:
        raise ValueError("В SVG нет глифов")
    kinds = classify_fonts(glyphs, [(f, c) for f, c, _, _ in uses])
    # оценка кегля каждого шрифта
    fsize = {}
    for f in {u[0] for u in uses}:
        est = []
        for (ff, c), g in glyphs.items():
            if ff != f:
                continue
            ch, _ = char_for(kinds.get(f, "mi"), c)
            if ch in REF_H and g.y1 > g.y0:
                est.append((g.y1 - g.y0) / REF_H[ch])
            elif kinds.get(f) == "cyr" and len(ch) == 1 and ch.lower() in "аеномрсувхзк" and g.y1 > g.y0:
                est.append((g.y1 - g.y0) / (0.43 if ch.islower() else 0.683))
        if est:
            fsize[f] = statistics.median(est)
    base_size = statistics.median(fsize.values()) if fsize else 10.0
    sizes_sorted = sorted(fsize.values())
    if sizes_sorted:
        base_size = max(sizes_sorted)
    els = []
    for f, c, x, y in uses:
        g = glyphs.get((f, c))
        if g is None:
            continue
        ch, kind = char_for(kinds.get(f, "mi"), c)
        size = fsize.get(f, base_size)
        els.append(El(ch, x + g.x0, y + g.y0, x + g.x1, y + g.y1, y, size, kind, f, c))
    # размер для элементов без оценки — по соседям
    for e in els:
        if e.font not in fsize:
            near = sorted((abs(o.cx - e.cx), o.size) for o in els if o.font in fsize)
            if near:
                e.size = near[0][1]
    return _layout(els, rects, base_size)


def _layout(els, rects, base):
    els = list(els)
    rects = sorted(rects, key=lambda r: r[2] - r[0])
    # черты от узких к широким: черта корня (у правого края знака корня) или черта дроби
    for r in rects:
        rw, rh = r[2] - r[0], r[3] - r[1]
        if rw < rh * 2.5:
            continue
        rad = [e for e in els if e.kind == "sqrt" and abs(r[0] - e.x1) < base * 0.3 and abs(r[1] - e.y0) < base * 0.35]
        if rad:
            e = rad[0]
            inside = [o for o in els if o is not e and o.x0 >= r[0] - base * 0.08 and o.x1 <= r[2] + base * 0.08
                      and o.y0 >= r[1] - base * 0.08 and o.y1 <= e.y1 + base * 0.08]
            for o in inside:
                els.remove(o)
            els.remove(e)
            els.append(El(r"\sqrt{" + _line(inside, base) + "}", e.x0, r[1], r[2], e.y1,
                          _main_base(inside, e.y1), base, "group"))
            continue
        ym = (r[1] + r[3]) / 2
        span = [o for o in els if r[0] - 0.5 <= o.cx <= r[2] + 0.5]
        num = _chain([o for o in span if o.y1 <= ym + 0.3], ym, up=True, base=base)
        den = _chain([o for o in span if o.y0 >= ym - 0.3], ym, up=False, base=base)
        if not num or not den:
            continue
        for o in num + den:
            els.remove(o)
        tex = r"\frac{" + _line(num, base) + "}{" + _line(den, base) + "}"
        els.append(El(tex, r[0], min(o.y0 for o in num), r[2], max(o.y1 for o in den), ym + base * 0.25, base, "group"))
    # векторы: стрелка над символом
    for a in [e for e in els if e.kind == "accent"]:
        under = [o for o in els if o is not a and o.kind != "accent" and o.y0 >= a.y1 - base * 0.25
                 and o.x0 - base * 0.15 <= a.cx <= o.x1 + base * 0.15]
        if not under:
            continue
        b = min(under, key=lambda o: o.y0 - a.y1)
        els.remove(a)
        els.remove(b)
        cmd = {"VEC": r"\vec", "TILDE": r"\tilde", "HAT": r"\hat"}[a.tex]
        els.append(El(f"{cmd}{{{b.tex}}}", min(a.x0, b.x0), a.y0, max(a.x1, b.x1), b.y1, b.base, b.size, "sym"))
    # системы: большая фигурная скобка слева
    braces = [e for e in els if e.kind == "brace" or (e.kind == "delim" and e.tex == r"\{" and (e.y1 - e.y0) > base * 1.6)]
    if braces:
        bx0 = min(e.x0 for e in braces)
        bx1 = max(e.x1 for e in braces)
        by0 = min(e.y0 for e in braces)
        by1 = max(e.y1 for e in braces)
        for e in braces:
            els.remove(e)
        left = [e for e in els if e.x1 <= bx0 + 0.5]
        right = [e for e in els if e.x0 >= bx1 - 0.5 and e.y0 >= by0 - base and e.y1 <= by1 + base]
        rest = [e for e in els if e not in left and e not in right]
        rows = _rows(right, base)
        body = r" \\ ".join(_line(r, base) for r in rows)
        out = (_line(left, base) + " " if left else "") + r"\begin{cases} " + body + r" \end{cases}"
        if rest:
            out += " " + _line(rest, base)
        return _clean(out)
    rows = _rows(els, base)
    if len(rows) > 1:
        return _clean(r" \\ ".join(_line(r, base) for r in rows))
    return _clean(_line(els, base))


def _main_base(items, default):
    if not items:
        return default
    return statistics.median(o.base for o in items)


def _chain(cands, ym, up, base):
    """Элементы над/под чертой дроби, связанные по вертикали с чертой."""
    if not cands:
        return []
    cands = sorted(cands, key=lambda o: (ym - o.y1) if up else (o.y0 - ym))
    edge = ym
    out = []
    for o in cands:
        gap = (edge - o.y1) if up else (o.y0 - edge)
        if gap <= base * 0.6 or (out and ((o.y1 >= min(x.y0 for x in out) - base * 0.1) if up else (o.y0 <= max(x.y1 for x in out) + base * 0.1))):
            out.append(o)
            edge = min(edge, o.y0) if up else max(edge, o.y1)
    return out


def _rows(items, base):
    items = sorted(items, key=lambda o: o.base)
    rows = []
    for o in items:
        if rows and abs(o.base - statistics.median(x.base for x in rows[-1])) < base * 0.9:
            rows[-1].append(o)
        elif rows and o.size < base * 0.85 and abs(o.cy - statistics.median(x.cy for x in rows[-1])) < base * 1.2:
            rows[-1].append(o)
        else:
            rows.append([o])
    # строки из одних индексов приклеиваем к ближайшей
    merged = []
    for r in rows:
        if merged and all(o.size < base * 0.85 for o in r):
            merged[-1].extend(r)
        else:
            merged.append(r)
    return merged


def _line(items, base):
    """Одна строка: индексы/степени по смещению базовой линии и кеглю, кириллица в \\text{}."""
    items = sorted(items, key=lambda o: o.x0)
    if not items:
        return ""
    big = [o for o in items if o.size >= base * 0.85 and o.kind not in ("group",)] or items
    main = statistics.median(o.base for o in big)
    parts = []
    prev = None
    last_main = None
    i = 0
    while i < len(items):
        o = items[i]
        small = o.size < base * 0.85 and o.kind != "group"
        if small and last_main is not None:
            sub = o.base > main + base * 0.05
            run = [o]
            j = i + 1
            while j < len(items) and items[j].size < base * 0.85 and items[j].kind != "group" and \
                    ((items[j].base > main + base * 0.05) == sub) and items[j].x0 - run[-1].x1 < base * 0.35:
                run.append(items[j])
                j += 1
            inner = _simple(run, o.size)
            parts.append(("_" if sub else "^") + "{" + inner + "}")
            prev = run[-1]
            i = j
            continue
        if prev is not None:
            gap = o.x0 - prev.x1
            if o.kind in ("cyr", "cyrtext") and prev.kind in ("cyr", "cyrtext"):
                if gap > o.size * 0.18:
                    parts.append(("CYR", " "))
            elif gap > base * 0.28 and o.kind not in ("delim",) and prev.tex not in ("(", "[") and \
                    not _is_op(o.tex) and not _is_op(prev.tex):
                parts.append(r"\ ")
        if o.kind in ("cyr", "cyrtext"):
            parts.append(("CYR", o.tex))
        else:
            parts.append(o.tex)
        prev = o
        last_main = o
        i += 1
    # склеиваем кириллицу в \text{}
    out = []
    buf = None
    for p in parts:
        if isinstance(p, tuple):
            buf = (buf or "") + p[1]
        else:
            if buf is not None:
                out.append(r"\text{" + buf.strip() + "}" if buf.strip() else r"\ ")
                buf = None
            out.append(p)
    if buf is not None and buf.strip():
        out.append(r"\text{" + buf.strip() + "}")
    s = ""
    for p in out:
        if s and re.match(r"[A-Za-z]", p[:1]) and re.search(r"\\[A-Za-z]+$", s):
            s += " "
        s += p
    return s


def _simple(items, size):
    s = ""
    prev = None
    for o in sorted(items, key=lambda o: o.x0):
        t = o.tex
        if o.kind in ("cyr", "cyrtext"):
            t = r"\text{" + t + "}"
        if s and re.match(r"[A-Za-z]", t[:1]) and re.search(r"\\[A-Za-z]+$", s):
            s += " "
        s += t
        prev = o
    return s


_OPS = {"+", "-", "=", r"\cdot", r"\times", r"\approx", r"\pm", r"\leq", r"\geq", r"\sim", r"\rightarrow", "<", ">",
        ",", ".", ":", ";", "/", r"\equiv", r"\neq", r"\Rightarrow"}


def _is_op(t):
    return t in _OPS


def _clean(s):
    s = s.replace(r"\text{}", "")
    s = re.sub(r"(\\ )+", r"\\ ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(r"\text{ ", r"\ \text{")
    return s
