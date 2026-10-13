# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Пути, настройки приложения и их сохранение."""
import copy
import json
import os
from pathlib import Path

import sys

APP_NAME = "RedColor"
APP_VERSION = "1.1"
AUTHOR_NAME = "Maksim Belonoskin"
AUTHOR = "Maksim Belonoskin, Zelenograd, Moscow, Russia"
COPYRIGHT = f"© 2026 {AUTHOR}"
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else APP_DIR
ASSETS = APP_DIR / "assets"
# пользовательские данные (цитаты, подписи, настройки, свои шрифты) — отдельно от программы
DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "RedColor"
SIG_DIR = DATA_DIR / "signatures"
SETTINGS_FILE = DATA_DIR / "settings.json"
USER_FONTS = DATA_DIR / "fonts"
QUOTES_FILE = DATA_DIR / "цитаты.txt"
for _d in (DATA_DIR, SIG_DIR, USER_FONTS):
    _d.mkdir(parents=True, exist_ok=True)

ACROBAT_FONT_DIR = Path(r"C:\Program Files\Adobe\Acrobat DC\Resource\Font")

DEFAULTS = {
    "theme": "dark",
    "accent": "#2680eb",
    # Текст
    "text_color": "#ff0000",
    "text_font": "Minion Pro",
    "text_size_auto": True,
    "text_size": 12.0,
    "auto_size_pct": 2.0,          # размер шрифта = % ширины страницы (A4 → ~12 pt)
    "text_bold": False,
    "text_italic": False,
    "text_align": "left",
    # Рисование
    "ink_color": "#ff0000",
    "ink_width": 1.5,
    "hl_color": "#ffd400",
    "hl_width": 12.0,
    "shape_color": "#ff0000",
    "shape_width": 1.5,
    # Цитаты и бланки
    "quotes_file": str(QUOTES_FILE),
    "blanks_dir": "",
    "auto_quote_on_blank": True,
    "remove_stray_one": True,
    "auto_remove_ones": True,
    "quote_font": "Minion Pro",
    "quote_default_size": 16.0,
    "quote_bag": [],
    "blank_zones": {},
    # Прочее
    "shortcuts": {},
    "recent": [],
    "last_dir": "",
    "geometry": "",
    "left_panel": True,
    "left_tab": 1,
    "signature_color": "",
    "zoom_mode": "auto",
}


class Settings(dict):
    def __init__(self):
        super().__init__(copy.deepcopy(DEFAULTS))
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.update(data)
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self, f, ensure_ascii=False, indent=1)
            os.replace(tmp, SETTINGS_FILE)
        except OSError:
            pass

    def add_recent(self, path):
        path = str(path)
        rec = [p for p in self.get("recent", []) if p != path]
        rec.insert(0, path)
        self["recent"] = rec[:15]
        self.save()


S = Settings()


def _migrate_quotes():
    """Старые версии хранили цитаты рядом с программой — переносим в папку данных пользователя."""
    cur = Path(S.get("quotes_file") or QUOTES_FILE)
    if cur != QUOTES_FILE and cur.exists() and not QUOTES_FILE.exists():
        try:
            QUOTES_FILE.write_text(cur.read_text(encoding="utf-8-sig"), encoding="utf-8")
            S["quotes_file"] = str(QUOTES_FILE)
            S.save()
        except OSError:
            pass
    elif not cur.exists() and cur != QUOTES_FILE:
        S["quotes_file"] = str(QUOTES_FILE)
        S.save()


_migrate_quotes()
