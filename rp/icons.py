# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Векторные иконки интерфейса (собственные, в стиле тонких линий)."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "cursor": '<path d="M6 3.5l12.5 9.2-5.6.9 3.2 6.2-2.3 1.2-3.2-6.3-4.1 3.9z" fill="currentColor" stroke="none"/>',
    "hand": '<path d="M8 12V5.5a1.5 1.5 0 0 1 3 0V11M11 10V4a1.5 1.5 0 0 1 3 0v7M14 10V5.5a1.5 1.5 0 0 1 3 0V13c0 4-2.5 7-6 7-2.5 0-4-1.2-5.5-3.5L3.8 13a1.4 1.4 0 0 1 2.3-1.6L8 14"/>',
    "text": '<path d="M3.5 6.5V4h11v2.5M9 4v14M6.5 18h5"/><path d="M18 13v7M14.5 16.5h7"/>',
    "image": '<rect x="3" y="4.5" width="18" height="15" rx="1.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16.5l-5-5L5 19.5"/>',
    "pencil": '<path d="M4 20l1.2-4.6L15.6 5a2 2 0 0 1 2.8 0l.6.6a2 2 0 0 1 0 2.8L8.6 18.8z"/><path d="M14 6.6l3.4 3.4"/>',
    "highlighter": '<path d="M9.5 14.5l-2 2 1 1-2.5 2.5H3l3-3 1-1-1-1 2-2"/><path d="M8 13l7.5-9.5 5 4L11 15z"/><path d="M13 21h8"/>',
    "eraser": '<path d="M8.5 20h11.5"/><path d="M4.3 14.7l9.4-9.4a1.5 1.5 0 0 1 2.1 0l3.9 3.9a1.5 1.5 0 0 1 0 2.1L12 19.5H8.6z"/><path d="M9.5 9.5l6 6"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="6.5"/>',
    "ellipse_num": '<ellipse cx="10" cy="14" rx="7.5" ry="5.5"/><path d="M18 3.5l1.5-1v6M18 8.5h3"/>',
    "rect": '<rect x="3.5" y="6" width="17" height="12" rx="1"/>',
    "line": '<path d="M5 19L19 5"/>',
    "arrow": '<path d="M5 19L19 5M10.5 5H19v8.5"/>',
    "check": '<path d="M4.5 12.5l4.5 4.5L19.5 6.5"/>',
    "cross": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "dot": '<circle cx="12" cy="12" r="4.5" fill="currentColor"/>',
    "shapes": '<rect x="3.5" y="10.5" width="9" height="9" rx="1"/><circle cx="16" cy="8" r="4.5"/>',
    "symbols": '<path d="M3.5 8.5l3 3 6-6.5"/><path d="M14 14l6 6M20 14l-6 6"/><path d="M6.5 15v6M3.5 18h6"/>',
    "sign": '<path d="M14.5 4.5l5 5L10 19l-5.5 1 1-5.5z"/><path d="M12.5 6.5l5 5"/><path d="M3 22h18" stroke-width="1.2"/>',
    "quote": '<path d="M5 17c2.5-.5 4-2.6 4-5.5V7H4.5v5H8"/><path d="M14 17c2.5-.5 4-2.6 4-5.5V7h-4.5v5H17"/>',
    "more": '<circle cx="5.5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="18.5" cy="12" r="1.6" fill="currentColor"/>',
    "rotate_cw": '<path d="M19.5 4.5v5h-5"/><path d="M19.3 9.5A8 8 0 1 0 20 14"/>',
    "rotate_ccw": '<path d="M4.5 4.5v5h5"/><path d="M4.7 9.5A8 8 0 1 1 4 14"/>',
    "page_insert": '<path d="M13.5 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8.5z"/><path d="M13.5 3v5.5H19"/><path d="M12 11.5v6M9 14.5h6"/>',
    "page_blank": '<path d="M13.5 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8.5z"/><path d="M13.5 3v5.5H19"/>',
    "trash": '<path d="M4 6.5h16M9.5 6.5V4h5v2.5"/><path d="M6 6.5l1 13.5h10l1-13.5"/><path d="M10 10.5v6M14 10.5v6"/>',
    "extract": '<path d="M13 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h10a1.5 1.5 0 0 0 1.5-1.5V17"/><path d="M13 3l5 5v1.5"/><path d="M10.5 13h11M18.5 10l3 3-3 3"/>',
    "organize": '<rect x="3.5" y="3.5" width="7" height="8" rx="1"/><rect x="13.5" y="3.5" width="7" height="8" rx="1"/><rect x="3.5" y="14.5" width="7" height="6" rx="1"/><path d="M14 17.5h6M17 14.5v6"/>',
    "blank": '<path d="M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8.5 7.5h7M8.5 11h7M8.5 14.5h4"/><path d="M14 17.5l1.5 1.5 3-3"/>',
    "open": '<path d="M3.5 19.5V5.5A1.5 1.5 0 0 1 5 4h4.5l2 2.5H18a1.5 1.5 0 0 1 1.5 1.5v2"/><path d="M3.5 19.5L6.3 11a1.5 1.5 0 0 1 1.4-1h13.1a1 1 0 0 1 1 1.3l-2.4 8.2H3.5z"/>',
    "save": '<path d="M5 3.5h11.5l4 4V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V5A1.5 1.5 0 0 1 5 3.5z"/><path d="M7.5 3.5v5h8v-5M7 20.5v-7h10v7"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21M10.5 7.5v6M7.5 10.5h6"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21M7.5 10.5h6"/>',
    "fit_width": '<path d="M3 4v16M21 4v16M6.5 12h11M9 9l-3 3 3 3M15 9l3 3-3 3"/>',
    "fit_page": '<rect x="6" y="3" width="12" height="18" rx="1"/><path d="M9.5 8.5l2.5-2.5 2.5 2.5M9.5 15.5l2.5 2.5 2.5-2.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chevron_up": '<path d="M6 15l6-6 6 6"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "chevron_left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="1.5"/><path d="M6 9.5h1M9.5 9.5h1M13 9.5h1M16.5 9.5h1M6 12.5h1M9.5 12.5h1M13 12.5h1M16.5 12.5h1M8 15.5h8"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "export": '<path d="M12 15V3.5M7.5 8L12 3.5 16.5 8"/><path d="M4 13.5V19a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-5.5"/>',
    "compress": '<path d="M9 3.5v5.5H3.5M15 3.5v5.5h5.5M9 20.5V15H3.5M15 20.5V15h5.5"/>',
    "merge": '<rect x="3" y="3.5" width="8" height="11" rx="1"/><rect x="13" y="9.5" width="8" height="11" rx="1"/><path d="M7 17.5v2a1 1 0 0 0 1 1h3M17 6.5v-2a1 1 0 0 0-1-1h-3"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/>',
    "menu": '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
    "pdf": '<path d="M13.5 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8.5z"/><path d="M13.5 3v5.5H19"/><path d="M8 17v-4h1.3a1.2 1.2 0 0 1 0 2.4H8M12 17v-4h1a2 2 0 0 1 0 4zM16 17v-4h2M16 15h1.5"/>',
    "edit_doc": '<path d="M12 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V12"/><path d="M17.5 3.5l3 3L13 14l-3.5.5.5-3.5z"/>',
    "convert": '<path d="M4 8h13M14 4.5L17.5 8 14 11.5M20 16H7M10 12.5L6.5 16l3.5 3.5"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.3 0 1.8-.8 1.8-1.7 0-1.4-1.2-1.6-1.2-2.8 0-1 .8-1.7 1.8-1.7H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.2" fill="currentColor"/><circle cx="10.5" cy="7" r="1.2" fill="currentColor"/><circle cx="15.5" cy="7.5" r="1.2" fill="currentColor"/>',
    "bold": '<path d="M7 4.5h6a3.5 3.5 0 0 1 0 7H7zM7 11.5h7a4 4 0 0 1 0 8H7z" stroke-width="2.2"/>',
    "italic": '<path d="M10 4.5h8M6 19.5h8M14.5 4.5l-5 15"/>',
    "align_left": '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    "align_center": '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    "align_right": '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    "fit_text": '<path d="M4 4h16v16H4z" stroke-dasharray="2 2"/><path d="M8 8.5h8M12 8.5v8"/>',
    "dice": '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><circle cx="8.5" cy="8.5" r="1.3" fill="currentColor"/><circle cx="15.5" cy="15.5" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/>',
    "folder": '<path d="M3.5 18.5V5.5A1.5 1.5 0 0 1 5 4h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v10.5A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    "star": '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "home": '<path d="M4 11l8-7 8 7"/><path d="M6 9.5V20h4.5v-6h3v6H18V9.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.7"/><circle cx="12" cy="17" r=".9" fill="currentColor"/>',
    "print": '<path d="M7 9V3.5h10V9"/><rect x="3.5" y="9" width="17" height="8" rx="1.5"/><path d="M7 14h10v6.5H7z"/>',
    "upload": '<path d="M12 16V5M7.5 9.5L12 5l4.5 4.5"/><path d="M6 13.5a4 4 0 0 0 1 7.5h10a4 4 0 0 0 1-7.8"/>',
    "win_min": '<path d="M5 12h14" stroke-width="1.1"/>',
    "win_max": '<rect x="5.5" y="5.5" width="13" height="13" stroke-width="1.1"/>',
    "win_restore": '<rect x="5.5" y="8" width="10.5" height="10.5" stroke-width="1.1"/><path d="M8 8V5.5h10.5V16H16" stroke-width="1.1"/>',
    "win_close": '<path d="M6 6l12 12M18 6L6 18" stroke-width="1.1"/>',
    "pages": '<rect x="7" y="3.5" width="12" height="15" rx="1"/><path d="M5 6.5v13a1 1 0 0 0 1 1h10"/>',
    "formula": '<path d="M5 18l3-1 3-12h4M7 10h6"/><path d="M14 13l5 6M19 13l-5 6"/>',
    "zone": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M8 10h8M8 14h5"/>',
}

_cache = {}


def svg(name, color="#e8e8e8"):
    body = _P.get(name, _P["more"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
        f'color="{color}">{body.replace("currentColor", color)}</svg>'
    )


def pixmap(name, size=20, color="#e8e8e8", dpr=2.0):
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name, color=None, disabled=None):
    from .theme import T
    color = color or T["icon"]
    disabled = disabled or T["icon_dis"]
    key = (name, color, disabled)
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon()
        for s in (16, 20, 24, 32):
            ic.addPixmap(pixmap(name, s, color), QIcon.Normal, QIcon.Off)
            ic.addPixmap(pixmap(name, s, color), QIcon.Normal, QIcon.On)
            ic.addPixmap(pixmap(name, s, disabled), QIcon.Disabled, QIcon.Off)
        _cache[key] = ic
    return ic


def clear_cache():
    _cache.clear()
