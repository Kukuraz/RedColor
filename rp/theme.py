# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Тёмная/светлая тема в стиле современного PDF-редактора."""
from .config import S

DARK = {
    "bg": "#1b1b1b", "canvas": "#1e1e1e", "panel": "#2b2b2b", "panel2": "#323232",
    "bar": "#232323", "border": "#3d3d3d", "border2": "#4a4a4a", "text": "#f0f0f0",
    "text2": "#c6c6c6", "text3": "#8f8f8f", "hover": "#3a3a3a", "press": "#454545",
    "icon": "#e8e8e8", "icon_dis": "#6a6a6a", "input": "#1f1f1f", "page_shadow": "#000000",
    "menu": "#2f2f2f", "tooltip": "#5a5a5a",
}
LIGHT = {
    "bg": "#f3f3f3", "canvas": "#e4e4e4", "panel": "#ffffff", "panel2": "#f5f5f5",
    "bar": "#fafafa", "border": "#dadada", "border2": "#c8c8c8", "text": "#1f1f1f",
    "text2": "#404040", "text3": "#7a7a7a", "hover": "#ececec", "press": "#e0e0e0",
    "icon": "#2c2c2c", "icon_dis": "#b0b0b0", "input": "#ffffff", "page_shadow": "#7a7a7a",
    "menu": "#ffffff", "tooltip": "#3a3a3a",
}

T = dict(DARK)


def apply_palette():
    T.clear()
    T.update(LIGHT if S.get("theme") == "light" else DARK)
    T["accent"] = S.get("accent", "#2680eb")


apply_palette()


def qss():
    t = T
    return f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable", sans-serif; font-size: 13px; color: {t['text']}; }}
QMainWindow, QWidget#root {{ background: {t['bg']}; }}
QToolTip {{ background: {t['tooltip']}; color: #ffffff; border: none; padding: 4px 8px; border-radius: 4px; }}
QMenu {{ background: {t['menu']}; border: 1px solid {t['border2']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t['hover']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 6px; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::right-arrow {{ width: 8px; height: 8px; }}

#topbar {{ background: {t['bar']}; border-bottom: 1px solid {t['border']}; }}
#toolbar2 {{ background: {t['bar']}; border-bottom: 1px solid {t['border']}; }}
#leftpanel {{ background: {t['panel']}; border-right: 1px solid {t['border']}; }}
#leftpanel QLabel#title {{ font-size: 16px; font-weight: 700; }}
#leftpanel QLabel#section {{ font-size: 11px; font-weight: 700; color: {t['text2']}; letter-spacing: 0.4px; }}
#sep {{ background: {t['border']}; max-height: 1px; min-height: 1px; }}

QTabBar#doctabs {{ background: transparent; }}
QTabBar#doctabs::tab {{ background: transparent; border: 1px solid transparent; border-bottom: none;
    padding: 6px 10px; margin-right: 2px; color: {t['text2']}; border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 120px; max-width: 260px; }}
QTabBar#doctabs::tab:selected {{ background: {t['panel2']}; color: {t['text']}; border-color: {t['border']}; }}
QTabBar#doctabs::tab:hover:!selected {{ background: {t['hover']}; }}

QPushButton#modetab {{ background: transparent; border: none; border-bottom: 2px solid transparent; padding: 9px 14px 8px 14px;
    color: {t['text2']}; font-size: 14px; border-radius: 0; }}
QPushButton#modetab:hover {{ color: {t['text']}; }}
QPushButton#modetab:checked {{ color: {t['text']}; border-bottom: 2px solid {t['text']}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['press']}; }}
QToolButton:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#panelrow {{ text-align: left; padding: 6px 8px; border-radius: 6px; font-size: 13px; }}
QToolButton#panelrow:checked {{ background: {t['hover']}; border-color: {t['border2']}; }}

#floatbar {{ background: {t['panel']}; border: 1px solid {t['border2']}; border-radius: 10px; }}
#floatbar QToolButton {{ border-radius: 6px; padding: 5px; }}
#grip {{ background: {t['border2']}; border-radius: 2px; }}
#pagenav {{ background: {t['panel']}; border: 1px solid {t['border2']}; border-radius: 10px; }}

QPushButton {{ background: {t['panel2']}; border: 1px solid {t['border2']}; border-radius: 15px; padding: 5px 16px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['press']}; }}
QPushButton#primary {{ background: {t['accent']}; border-color: {t['accent']}; color: #ffffff; font-weight: 600; }}
QPushButton#primary:hover {{ background: {t['accent']}; border-color: #ffffff; }}
QPushButton#flat {{ background: transparent; border: none; border-radius: 6px; padding: 5px 8px; text-align: left; }}
QPushButton#flat:hover {{ background: {t['hover']}; }}
QPushButton:disabled {{ color: {t['text3']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QKeySequenceEdit QLineEdit {{
    background: {t['input']}; border: 1px solid {t['border2']}; border-radius: 5px; padding: 4px 6px;
    selection-background-color: {t['accent']}; selection-color: #ffffff; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {t['menu']}; border: 1px solid {t['border2']}; selection-background-color: {t['hover']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t['text3']}; border-radius: 3px; background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['border2']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {t['text']}; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['border2']}; border-radius: 4px; min-height: 30px; margin: 2px 3px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text3']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t['border2']}; border-radius: 4px; min-width: 30px; margin: 3px 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget, QTableWidget, QTreeWidget {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 6px; outline: none; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {t['hover']}; color: {t['text']}; }}
QHeaderView::section {{ background: {t['panel2']}; border: none; border-bottom: 1px solid {t['border']}; padding: 5px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {t['text2']}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
QDialog {{ background: {t['panel']}; }}
QStatusBar {{ background: {t['bar']}; color: {t['text3']}; }}
QSplitter::handle {{ background: {t['border']}; }}
QScrollArea {{ border: none; background: transparent; }}
#scrollinner {{ background: transparent; }}
QGraphicsView {{ border: none; background: {t['canvas']}; }}
QListWidget#thumbs {{ background: {t['canvas']}; border: none; }}
#homepage {{ background: {t['canvas']}; }}
#card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 12px; }}
"""
