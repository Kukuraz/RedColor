# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Реестр шрифтов: системные (с кириллицей), шрифты Акробата и свои из папки fonts."""
import hashlib
import json
import os
import re
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF

from .config import ACROBAT_FONT_DIR, DATA_DIR, USER_FONTS

FAVORITES = ["Minion Pro", "Times New Roman", "Arial", "Calibri", "Segoe Print", "Segoe Script",
             "Gabriola", "Comic Sans MS", "Georgia", "Myriad Pro", "Verdana", "Caveat", "Marck Script",
             "Bad Script", "Pacifico", "Lobster", "Amatic SC"]
PRETTY = {"Segoe Print", "Segoe Script", "Gabriola", "Caveat", "Marck Script", "Bad Script",
          "Pacifico", "Lobster", "Amatic SC", "Comic Sans MS"}

_families = {}      # family -> {"r": path, "b": path, "i": path, "bi": path}
_qt_names = {}      # family -> qt family name
_loaded_files = {}  # path -> qt family
_CACHE = DATA_DIR / "fonts_cache.json"
_STYLE_RE = re.compile(r"\s+(Bold Italic|Bold Oblique|Bold|Italic|Oblique)$", re.I)


def _reg_fonts():
    import winreg
    out = []
    win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for root, base in ((winreg.HKEY_LOCAL_MACHINE, win_fonts),
                       (winreg.HKEY_CURRENT_USER, None)):
        try:
            k = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            if not isinstance(val, str):
                continue
            p = Path(val)
            if not p.is_absolute():
                p = (base or win_fonts) / val
            if p.suffix.lower() not in (".ttf", ".otf"):
                continue
            name = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", name).strip()
            if "&" in name:
                continue
            out.append((name, str(p)))
    return out


def _style_key(name):
    m = _STYLE_RE.search(name)
    if not m:
        return name, "r"
    st = m.group(1).lower()
    fam = name[:m.start()].strip()
    if "bold" in st and ("italic" in st or "oblique" in st):
        return fam, "bi"
    if "bold" in st:
        return fam, "b"
    return fam, "i"


def _split_camel(s):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)


def _file_fonts(folder):
    """Шрифты из папки: имя семейства по имени файла (MinionPro-BoldIt.otf → Minion Pro, bi)."""
    out = []
    if not folder.exists():
        return out
    for p in folder.iterdir():
        if p.suffix.lower() not in (".ttf", ".otf"):
            continue
        stem = p.stem
        base, _, style = stem.partition("-")
        style = style.lower().replace("_", "")
        fam = _split_camel(base.replace("_", " ")).strip()
        fam = re.sub(r"\[.*\]", "", fam).strip()
        if style in ("", "regular", "roman", "book", "normal") or style.startswith("variable"):
            key = "r"
        elif style in ("bold", "bd"):
            key = "b"
        elif style in ("it", "italic", "oblique"):
            key = "i"
        elif style in ("boldit", "bolditalic", "bi"):
            key = "bi"
        else:
            fam = f"{fam} {_split_camel(stem.partition('-')[2])}"
            key = "r"
        out.append((fam, key, str(p)))
    return out


def _has_cyrillic(path, cache):
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = f"{st.st_size}:{int(st.st_mtime)}"
    c = cache.get(path)
    if c and c[0] == key:
        return c[1]
    try:
        import pymupdf
        f = pymupdf.Font(fontfile=path)
        ok = bool(f.has_glyph(0x0416) and f.has_glyph(0x044F))
    except Exception:
        ok = False
    cache[path] = [key, ok]
    return ok


def init():
    if _families:
        return
    try:
        cache = json.loads(_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    fams = {}
    for name, path in _reg_fonts():
        fam, key = _style_key(name)
        fams.setdefault(fam, {})[key] = path
    extra = {}
    for folder in (ACROBAT_FONT_DIR, USER_FONTS):
        for fam, key, path in _file_fonts(folder):
            extra.setdefault(fam, {})[key] = path
    fams.update(extra)
    for fam, v in fams.items():
        if "r" not in v:
            continue
        if _has_cyrillic(v["r"], cache):
            _families[fam] = v
    try:
        _CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def families():
    init()
    fav = [f for f in FAVORITES if f in _families]
    rest = sorted((f for f in _families if f not in fav), key=str.lower)
    return fav, rest


def exists(fam):
    init()
    return fam in _families


def resolve(fam):
    init()
    if fam in _families:
        return fam
    for f in ("Minion Pro", "Times New Roman", "Arial"):
        if f in _families:
            return f
    return next(iter(_families), "Arial")


def file_for(fam, bold=False, italic=False):
    init()
    v = _families.get(resolve(fam), {})
    key = "bi" if bold and italic else "b" if bold else "i" if italic else "r"
    return v.get(key) or (v.get("b") if bold else None) or (v.get("i") if italic else None) or v.get("r")


def pdf_name(path):
    return "F" + hashlib.md5(path.encode("utf-8")).hexdigest()[:10]


def qt_family(fam):
    """Регистрирует файлы семейства в Qt и возвращает имя семейства для QFont."""
    init()
    fam = resolve(fam)
    if fam in _qt_names:
        return _qt_names[fam]
    name = None
    for key in ("r", "b", "i", "bi"):
        p = _families.get(fam, {}).get(key)
        if not p:
            continue
        if p not in _loaded_files:
            fid = QFontDatabase.addApplicationFont(p)
            fl = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            _loaded_files[p] = fl[0] if fl else None
        if key == "r":
            name = _loaded_files[p]
    _qt_names[fam] = name or fam
    return _qt_names[fam]


_PT2QT = None


def pt_to_qt():
    """Коэффициент: QFont.pointSizeF = pt * k даёт ровно pt единиц сцены (1 ед. = 1 pt PDF)."""
    global _PT2QT
    if _PT2QT is None:
        a = QFont("Arial")
        a.setPointSizeF(100)
        b = QFont("Arial")
        b.setPixelSize(100)
        ha, hb = QFontMetricsF(a).height(), QFontMetricsF(b).height()
        _PT2QT = (hb / ha) if ha > 0 else 0.75
    return _PT2QT


def make_qfont(fam, size, bold=False, italic=False):
    f = QFont(qt_family(fam))
    f.setPointSizeF(max(0.5, size) * pt_to_qt())
    f.setBold(bold)
    f.setItalic(italic)
    f.setHintingPreference(QFont.PreferNoHinting)
    f.setKerning(False)
    return f
