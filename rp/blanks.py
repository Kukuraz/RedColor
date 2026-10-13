# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Бланки проверки и случайные цитаты.

При вставке бланка: красная «1» (остаток текстового поля) удаляется, а на её место тем же шрифтом
и размером ставится случайная цитата. Если «1» нет — цитата встаёт под надписью «Комментарий эксперта:».
"""
import os
import random
from pathlib import Path

import numpy as np
import pymupdf

from .config import ASSETS, QUOTES_FILE, S

DPI = 50


# =========================================================================== цитаты
class QuoteBank:
    def __init__(self):
        self.path = None
        self.quotes = []
        self.reload()

    def reload(self):
        p = Path(S.get("quotes_file") or QUOTES_FILE)
        self.path = p
        try:
            txt = p.read_text(encoding="utf-8-sig")
        except OSError:
            txt = ""
        self.quotes = [l.strip() for l in txt.splitlines() if l.strip()]

    def save(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text((text.strip() + "\n") if text.strip() else "", encoding="utf-8")
        S["quote_bag"] = []
        self.reload()

    def next(self):
        """Случайная цитата без повторов, пока не пройдём весь список."""
        if not self.quotes:
            return None
        bag = [i for i in S.get("quote_bag", []) if isinstance(i, int) and 0 <= i < len(self.quotes)]
        if not bag:
            bag = list(range(len(self.quotes)))
            random.shuffle(bag)
        i = bag.pop()
        S["quote_bag"] = bag
        S.save()
        return self.quotes[i]


QUOTES = QuoteBank()


# =========================================================================== анализ бланка
_template = None


def _tpl():
    global _template
    if _template is None:
        from PIL import Image
        a = np.array(Image.open(ASSETS / "comment_label.png").convert("L"))
        _template = a < 128
    return _template


def _gray(page):
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, annots=True)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.stride)[:, :pix.w]


def _find_label(a):
    tn = _tpl()
    th, tw = tn.shape
    H, W = a.shape
    d = a < 128
    best = (1 << 30, 0, 0)
    for y in range(int(H * 0.3), max(int(H * 0.97) - th, int(H * 0.3) + 1)):
        rows = d[y:y + th]
        if rows.shape[0] < th:
            break
        for x in range(0, max(int(W * 0.2), 1)):
            win = rows[:, x:x + tw]
            if win.shape[1] < tw:
                break
            diff = np.count_nonzero(win ^ tn)
            if diff < best[0]:
                best = (diff, x, y)
    score, x, y = best
    if score > tn.sum() * 0.6:
        return None
    k = 72.0 / DPI
    return pymupdf.Rect(x * k, y * k, (x + tw) * k, (y + th) * k)


def _strays(page):
    """Короткие красные надписи (например, «1»), оставшиеся от текстовых полей."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                c = s["color"]
                r, g, bl = (c >> 16) & 255, (c >> 8) & 255, c & 255
                if t and len(t) <= 2 and r > 180 and g < 80 and bl < 80:
                    out.append({"rect": pymupdf.Rect(s["bbox"]), "size": s["size"], "font": s["font"],
                                "origin": s["origin"]})
    return out


_cache = {}


def analyze(path):
    """Возвращает dict: label, zone (Rect), strays, page size. Кешируется по времени изменения."""
    p = str(path)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        mt = 0
    c = _cache.get(p)
    if c and c[0] == mt:
        return c[1]
    doc = pymupdf.open(p)
    info = analyze_page(doc[0])
    manual = S.get("blank_zones", {}).get(Path(p).name)
    if manual:
        info["zone"] = pymupdf.Rect(manual)
    doc.close()
    _cache[p] = (mt, info)
    return info


def analyze_page(page, strays=None):
    """Разбор страницы-бланка: надпись «Комментарий эксперта:», поле комментария, красные «1»."""
    W, H = page.rect.width, page.rect.height
    a = _gray(page)
    label = _find_label(a)
    strays = _strays(page) if strays is None else strays
    zone = None
    if label is not None:
        k = DPI / 72.0
        top = label.y1 + 3
        ty = int(top * k)
        bottom = H - 30
        lx0, lx1 = int(label.x0 * k), int((label.x0 + 60) * k)
        for y in range(ty + int(12 * k), a.shape[0]):
            if np.count_nonzero(a[y, lx0:lx1] < 128) >= 2:
                bottom = y / k - 4
                break
        right = W - label.x0
        band = a[ty:int(bottom * k)]
        if band.size:
            col = (band < 215).mean(axis=0)
            start = int((label.x0 + 60) * k)
            for x in range(start, band.shape[1]):
                if col[x] > 0.2:
                    right = x / k - 8
                    break
        zone = pymupdf.Rect(label.x0, top, right, bottom)
    return {"label": label, "zone": zone, "strays": strays, "w": W, "h": H}


def comment_ones(page):
    """Красные «1» (и другие 1–2-символьные остатки) в поле «Комментарий эксперта» на странице-бланке."""
    if page.rotation:
        return []
    st = _strays(page)
    if not st:
        return []
    info = analyze_page(page, st)
    label = info["label"]
    if label is None:
        return []
    zone = info["zone"]
    bottom = zone.y1 + 6 if zone is not None else label.y1 + 220
    right = (zone.x1 + 30) if zone is not None else page.rect.width * 0.8
    out = []
    for s in st:
        r = s["rect"]
        cy = (r.y0 + r.y1) / 2
        if label.y0 - 4 <= cy <= bottom and r.x1 <= right:
            out.append(s)
    return out


def remove_comment_ones(page):
    """Удаляет найденные «1» из содержимого страницы. Возвращает их количество."""
    found = comment_ones(page)
    for s in found:
        r = pymupdf.Rect(s["rect"])
        r.x0 += 0.3
        r.x1 -= 0.3
        page.add_redact_annot(r)
    if found:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    return len(found)


def clean_blank_file(path, backup_dir):
    """Убирает «1» из файла бланка (оригинал копируется в backup_dir). Возвращает число удалённых."""
    import shutil
    path = Path(path)
    doc = pymupdf.open(str(path))
    n = sum(remove_comment_ones(pg) for pg in doc)
    if n:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst = backup_dir / path.name
        if not dst.exists():
            shutil.copy2(path, dst)
        tmp = path.with_suffix(".pdf.tmp")
        doc.save(str(tmp), garbage=3, deflate=True)
        doc.close()
        os.replace(tmp, path)
        _cache.pop(str(path), None)
    else:
        doc.close()
    return n


def blank_files():
    """Все PDF из папки бланков (с подпапками; папки, начинающиеся с «_», пропускаются)."""
    d = Path(S.get("blanks_dir") or "")
    if not str(S.get("blanks_dir") or "").strip() or not d.is_dir():
        return []
    out = []
    for p in d.rglob("*.pdf"):
        rel = p.relative_to(d)
        if any(part.startswith(("_", ".")) for part in rel.parts[:-1]):
            continue
        out.append(p)
    return sorted(out, key=lambda p: str(p.relative_to(d)).lower())


def blank_label(p):
    d = Path(S.get("blanks_dir") or "")
    try:
        rel = p.relative_to(d)
    except ValueError:
        return p.stem
    return str(rel.with_suffix("")).replace("\\", " / ")


def prepared_blank(path):
    """Копия бланка (fitz.Document) — с удалённой «1», если включено."""
    doc = pymupdf.open(str(path))
    if S.get("remove_stray_one", True):
        page = doc[0]
        st = _strays(page)
        if st:
            for s in st:
                page.add_redact_annot(s["rect"])
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    return doc


def quote_placement(info):
    """Куда и каким кеглем ставить цитату: (x, y_top, width, size, max_height) в pt бланка."""
    zone = info.get("zone")
    strays = info.get("strays") or []
    size = float(S.get("quote_default_size", 16.0))
    if strays:
        s = strays[0]
        size = float(s["size"])
        x, y = s["rect"].x0, s["rect"].y0
        right = zone.x1 if zone is not None else info["w"] - 40
        bottom = zone.y1 if zone is not None else y + size * 4
        return x, y, max(right - x, 80), size, max(bottom - y, size * 1.3)
    if zone is not None:
        return zone.x0, zone.y0, max(zone.width, 80), size, max(zone.height, size * 1.3)
    w, h = info["w"], info["h"]
    return w * 0.07, h * 0.7, w * 0.55, size, h * 0.15
