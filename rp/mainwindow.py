# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Главное окно RedColor."""
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication, QIcon, QImage, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCompleter, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)

from . import blanks, fonts, icons
from .config import APP_NAME, ASSETS, S
from .dialogs import FormulaDialog, HotkeysDialog, QuotesDialog, SettingsDialog
from .docwidget import DocumentWidget
from .document import IMG_EXT, DocModel
from .formula import REGISTRY
from .items import BoxItem, ImageItem, InkItem, ShapeItem, TextItem
from .panels import LeftPanel
from .shortcuts import Actions
from .signatures import STORE, SignatureDialog
from .theme import T, qss
from .widgets import IconButton

TOOLS = [
    ("select", "Выделение", "V", "cursor"), ("hand", "Рука", "H", "hand"), ("text", "Добавить текст", "T", "text"),
    ("pencil", "Карандаш", "P", "pencil"), ("highlighter", "Маркер", "U", "highlighter"),
    ("eraser", "Ластик", "E", "eraser"), ("ellipse", "Овал", "O", "ellipse"),
    ("ellipse_num", "Овал с номером", "N", "ellipse_num"), ("rect", "Прямоугольник", "R", "rect"),
    ("line", "Линия", "L", "line"), ("arrow", "Стрелка", "A", "arrow"), ("check", "Галочка ✓", "K", "check"),
    ("cross", "Крестик ✗", "X", "cross"), ("plus", "Плюс +", "=", "plus"), ("minus", "Минус –", "-", "minus"),
    ("dot", "Точка •", ".", "dot"), ("quote", "Случайная цитата", "Q", "quote"), ("formula", "Формула", "F", "formula"),
    ("image", "Изображение", "I", "image"), ("signature", "Поставить подпись", "S", "sign"),
]
ONE_SHOT = {"signature", "image", "formula", "quote"}


# =========================================================================== контекст инструментов
class Tools:
    def __init__(self, main):
        self.main = main
        self.tool = "select"
        self.signature_id = None

    def text_props(self, page=None):
        size = S["text_size"]
        if S["text_size_auto"]:
            w = page.w if page is not None else 595
            size = round(w * S["auto_size_pct"] / 100 * 2) / 2
        return {"font": fonts.resolve(S["text_font"]), "size": size, "color": S["text_color"],
                "bold": S["text_bold"], "italic": S["text_italic"], "align": S["text_align"]}

    def ink_color(self):
        return S["ink_color"]

    def ink_width(self):
        return S["ink_width"]

    def shape_color(self):
        return S["shape_color"]

    def shape_width(self):
        return S["shape_width"]

    def after_place(self):
        if self.tool in ONE_SHOT:
            self.main.set_tool("select")

    def place_quote(self, view, pi, pos):
        self.main.place_quote(view, pi, pos)

    def place_signature(self, view, pi, pos):
        self.main.place_signature(view, pi, pos)

    def place_image(self, view, pi, pos):
        self.main.place_image(view, pi, pos)

    def place_formula(self, view, pi, pos):
        self.main.place_formula(view, pi, pos)

    def edit_formula(self, view, item, pos):
        self.main.edit_formula(view, item, pos)

    def open_paths(self, paths):
        self.main.open_paths(paths)


# =========================================================================== шапка
class TitleBar(QFrame):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(38)
        self.main = main
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 0, 0, 0)
        h.setSpacing(4)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("Меню")
        self.menu_btn.setIcon(icons.icon("menu"))
        self.menu_btn.setIconSize(QSize(16, 16))
        self.menu_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setStyleSheet("font-size:12px;padding:4px 8px;")
        h.addWidget(self.menu_btn)
        self.home = IconButton("home", "Главная", 18)
        self.home.setFixedSize(34, 30)
        h.addWidget(self.home)
        self.tabs = QTabBar()
        self.tabs.setObjectName("doctabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.setDrawBase(False)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        h.addWidget(self.tabs, 0, Qt.AlignBottom)
        self.create = QToolButton()
        self.create.setText("Создать")
        self.create.setIcon(icons.icon("plus"))
        self.create.setIconSize(QSize(14, 14))
        self.create.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.create.setPopupMode(QToolButton.InstantPopup)
        self.create.setStyleSheet(f"QToolButton{{border:1px solid {T['border2']};border-radius:5px;padding:2px 8px;"
                                  f"font-size:12px;}}")
        h.addWidget(self.create)
        self.drag_area = QWidget()
        self.drag_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        h.addWidget(self.drag_area, 1)
        self.help = IconButton("help", "Информация: как пользоваться RedColor (F1)", 18)
        self.help.setFixedSize(34, 30)
        h.addWidget(self.help)
        h.addSpacing(8)
        self.btn_min = self._win_btn("win_min", main.showMinimized)
        self.btn_max = self._win_btn("win_max", main.toggle_max)
        self.btn_close = self._win_btn("win_close", main.close, close=True)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            h.addWidget(b)

    def _win_btn(self, ic, fn, close=False):
        b = QToolButton()
        b.setIcon(icons.icon(ic))
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(46, 38)
        hover = "#c42b1c" if close else T["hover"]
        b.setStyleSheet(f"QToolButton{{border:none;border-radius:0;}}QToolButton:hover{{background:{hover};}}")
        b.clicked.connect(fn)
        return b

    def is_drag_area(self, w, pos_in_self):
        if w is self or w is self.drag_area:
            return True
        if w is self.tabs:
            return self.tabs.tabAt(self.tabs.mapFrom(self, pos_in_self)) < 0
        return False

    def mouseDoubleClickEvent(self, e):
        self.main.toggle_max()


class ModeBar(QFrame):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("toolbar2")
        self.setFixedHeight(42)
        A = main.A
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 0, 10, 0)
        h.setSpacing(0)
        self.group = QButtonGroup(self)
        self.btns = {}
        for key, text in (("all", "Все инструменты"), ("edit", "Редактировать"), ("convert", "Преобразовать"),
                          ("sign", "Электронное подписание")):
            b = QPushButton(text)
            b.setObjectName("modetab")
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            self.btns[key] = b
            b.clicked.connect(lambda _=False, k=key: main.set_mode(k))
            h.addWidget(b)
        sep = QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet(f"background:{T['border2']}")
        h.addSpacing(8)
        h.addWidget(sep)
        h.addSpacing(8)
        for aid, ic in (("edit.undo", "undo"), ("edit.redo", "redo")):
            b = IconButton(ic, A[aid].toolTip(), 18, action=A[aid])
            b.setIcon(icons.icon(ic))
            b.setFixedSize(32, 30)
            h.addWidget(b)
        h.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти текст или инструмент")
        self.search.setFixedWidth(230)
        self.search.setStyleSheet("QLineEdit{background:transparent;border:none;padding:4px;}"
                                  f"QLineEdit:focus{{border-bottom:1px solid {T['accent']};}}")
        self.search.addAction(icons.icon("search"), QLineEdit.TrailingPosition)
        h.addWidget(self.search)
        sep2 = QFrame()
        sep2.setFixedSize(1, 20)
        sep2.setStyleSheet(f"background:{T['border2']}")
        h.addSpacing(6)
        h.addWidget(sep2)
        h.addSpacing(6)
        for aid, ic in (("file.save", "save"), ("file.save_as", "upload"), ("file.print", "print")):
            b = IconButton(ic, A[aid].toolTip(), 18, action=A[aid])
            b.setIcon(icons.icon(ic))
            b.setFixedSize(34, 30)
            h.addWidget(b)
        h.addSpacing(8)
        save = QPushButton("Сохранить")
        save.setStyleSheet(f"QPushButton{{background:{T['text2']};color:{T['bg']};border:none;border-radius:15px;"
                           f"padding:5px 16px;font-weight:700;}}QPushButton:hover{{background:{T['text']};}}")
        save.clicked.connect(A["file.save"].trigger)
        h.addWidget(save)


class HomePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("homepage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.main = main
        v = QVBoxLayout(self)
        v.setContentsMargins(60, 40, 60, 40)
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(760)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(32, 28, 32, 28)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS / "redcolor_256.png")).pixmap(56, 56))
        top.addWidget(logo)
        tl = QVBoxLayout()
        t = QLabel("RedColor")
        t.setStyleSheet("font-size:24px;font-weight:700")
        s = QLabel("Редактор PDF для проверки работ")
        s.setStyleSheet(f"color:{T['text2']}")
        tl.addWidget(t)
        tl.addWidget(s)
        top.addLayout(tl)
        top.addStretch(1)
        ob = QPushButton("Открыть файл")
        ob.setObjectName("primary")
        ob.clicked.connect(main.A["file.open"].trigger)
        top.addWidget(ob)
        cv.addLayout(top)
        cv.addSpacing(16)
        lab = QLabel("НЕДАВНИЕ ФАЙЛЫ")
        lab.setObjectName("section")
        lab.setStyleSheet(f"font-size:11px;font-weight:700;color:{T['text2']}")
        cv.addWidget(lab)
        self.recent = QListWidget()
        self.recent.setIconSize(QSize(20, 20))
        self.recent.itemActivated.connect(lambda it: main.open_paths([it.data(Qt.UserRole)]))
        self.recent.itemClicked.connect(lambda it: main.open_paths([it.data(Qt.UserRole)]))
        cv.addWidget(self.recent, 1)
        hint = QLabel("Перетащите PDF в окно, чтобы открыть. Ctrl+V — вставка текста и формул с сайта.")
        hint.setStyleSheet(f"color:{T['text3']}")
        cv.addWidget(hint)
        from .config import APP_VERSION, AUTHOR
        author = QLabel(f"RedColor {APP_VERSION} · Автор: {AUTHOR}")
        author.setStyleSheet(f"color:{T['text3']};font-size:11px")
        cv.addWidget(author)
        v.addWidget(card, 1, Qt.AlignHCenter)
        self.refresh()

    def refresh(self):
        self.recent.clear()
        for p in S.get("recent", []):
            if Path(p).exists():
                it = QListWidgetItem(icons.icon("pdf"), f"{Path(p).name}    —    {Path(p).parent}")
                it.setData(Qt.UserRole, p)
                self.recent.addItem(it)


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background:#3c3c3c;color:#ffffff;border-radius:8px;padding:8px 14px;")
        self.hide()
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.hide)

    def show_msg(self, text, ms=2600):
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 30)
        self.show()
        self.raise_()
        self._t.start(ms)


# =========================================================================== окно
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ASSETS / "redcolor.ico")))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAcceptDrops(True)
        self.tools = Tools(self)
        self.A = Actions(self)
        self.docs = []
        self.mode = "edit"
        self._build_menus()
        self._register_actions()
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.title = TitleBar(self)
        v.addWidget(self.title)
        self.modebar = ModeBar(self)
        v.addWidget(self.modebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.panel = LeftPanel(self)
        self.panel.close_requested.connect(lambda: self.toggle_panel(False))
        body.addWidget(self.panel)
        self.stack = QStackedWidget()
        self.home = HomePage(self)
        self.stack.addWidget(self.home)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.toast = Toast(self.stack)
        # шапка
        self.title.menu_btn.setMenu(self.app_menu)
        self.title.create.setMenu(self.create_menu)
        self.title.home.clicked.connect(self.show_home)
        self.title.help.clicked.connect(self.A["app.info"].trigger)
        self.title.tabs.currentChanged.connect(self._tab_changed)
        self.title.tabs.tabCloseRequested.connect(self.close_doc)
        self.title.tabs.tabMoved.connect(self._tab_moved)
        # панель форматирования
        self.panel.fmt.changed.connect(self.format_changed)
        self.panel.ink_color.color_changed.connect(self._ink_color)
        self.panel.ink_width.currentTextChanged.connect(self._ink_width)
        # поиск инструментов
        names = [self.A.meta[a][1] for a in self.A.ordered()]
        comp = QCompleter(names, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.modebar.search.setCompleter(comp)
        self.modebar.search.returnPressed.connect(self._search_enter)
        self.set_mode(["all", "edit", "convert", "sign"][min(S.get("left_tab", 1), 3)])
        self.toggle_panel(S.get("left_panel", True))
        self.set_tool("select")
        self._update_format_panel()
        self.rebuild_blank_actions()
        self.rebuild_signature_actions()
        self._place_window()
        if not S.get("info_shown"):
            S["info_shown"] = True
            S.save()
            QTimer.singleShot(900, self.show_info)
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def _focus_changed(self, *a):
        if not getattr(self, "_closing", False):
            try:
                self._update_format_panel()
            except RuntimeError:
                pass

    def _place_window(self):
        scr = QGuiApplication.primaryScreen().availableGeometry()
        restored = False
        if S.get("geometry"):
            try:
                from PySide6.QtCore import QByteArray
                restored = self.restoreGeometry(QByteArray.fromBase64(S["geometry"].encode()))
            except Exception:
                restored = False
        if restored:
            ok = any(sc.availableGeometry().intersects(self.frameGeometry()) for sc in QGuiApplication.screens())
            if ok and not S.get("maximized"):
                return
        w = min(1500, int(scr.width() * 0.92))
        h = min(980, int(scr.height() * 0.92))
        self.resize(w, h)
        self.move(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2)
        if S.get("maximized", True):
            QTimer.singleShot(0, self.showMaximized)

    # ================================================================ рамка окна (Windows)
    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_styled", False):
            self._styled = True
            try:
                hwnd = int(self.winId())
                GWL_STYLE = -16
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                style |= 0x00040000 | 0x00C00000 | 0x00020000 | 0x00010000 | 0x00080000
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)

                class MARGINS(ctypes.Structure):
                    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(1, 1, 1, 1)))
                val = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
            except Exception:
                pass

    def nativeEvent(self, et, msg):
        try:
            if et == b"windows_generic_MSG" or et == "windows_generic_MSG":
                m = wintypes.MSG.from_address(int(msg))
                if m.message == 0x0083 and m.wParam:          # WM_NCCALCSIZE
                    if self.isMaximized():
                        class RECT(ctypes.Structure):
                            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
                        r = RECT.from_address(m.lParam)
                        bx = ctypes.windll.user32.GetSystemMetrics(32) + ctypes.windll.user32.GetSystemMetrics(92)
                        by = ctypes.windll.user32.GetSystemMetrics(33) + ctypes.windll.user32.GetSystemMetrics(92)
                        r.l += bx
                        r.t += by
                        r.r -= bx
                        r.b -= by
                    return True, 0
                if m.message == 0x0084:                      # WM_NCHITTEST
                    pos = self.mapFromGlobal(QCursor.pos())
                    w, h = self.width(), self.height()
                    b = 6
                    if not self.isMaximized():
                        left, right = pos.x() < b, pos.x() > w - b
                        top, bottom = pos.y() < b, pos.y() > h - b
                        if top and left:
                            return True, 13
                        if top and right:
                            return True, 14
                        if bottom and left:
                            return True, 16
                        if bottom and right:
                            return True, 17
                        if left:
                            return True, 10
                        if right:
                            return True, 11
                        if top:
                            return True, 12
                        if bottom:
                            return True, 15
                    tp = self.title.mapFrom(self, pos)
                    if self.title.rect().contains(tp):
                        child = self.title.childAt(tp)
                        if child is None or self.title.is_drag_area(child, tp):
                            return True, 2                   # HTCAPTION
        except Exception:
            pass
        return super().nativeEvent(et, msg)

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self.title.btn_max.setIcon(icons.icon("win_restore" if self.isMaximized() else "win_max"))
        super().changeEvent(e)

    # ================================================================ меню
    def _build_menus(self):
        self.app_menu = QMenu(self)
        self.create_menu = QMenu(self)
        self.blank_menu = QMenu("Вставить бланк", self)
        self.blank_menu.setIcon(icons.icon("blank"))
        self.sign_menu = QMenu("Подписи", self)
        self.insert_menu = QMenu("Вставить страницы", self)
        self.org_insert_menu = QMenu("Вставить", self)
        self.recent_menu = QMenu("Открыть недавние", self)
        self.recent_menu.aboutToShow.connect(self._fill_recent)

    def _register_actions(self):
        A = self.A
        g = "Файл"
        A.add("file.open", "Открыть…", "Ctrl+O", self.open_dialog, "open", g)
        A.add("file.save", "Сохранить", "Ctrl+S", self.save, "save", g)
        A.add("file.save_as", "Сохранить как…", "Ctrl+Shift+S", self.save_as, "upload", g)
        A.add("file.close", "Закрыть документ", "Ctrl+W", lambda: self.close_doc(self.title.tabs.currentIndex()), "close", g)
        A.add("file.print", "Печать…", "Ctrl+P", self.print_doc, "print", g)
        A.add("file.new", "Пустой PDF", "Ctrl+N", self.new_blank_pdf, "page_blank", g)
        A.add("file.merge", "Объединение файлов", "", self.merge_files, "merge", g)
        A.add("file.compress", "Сжать PDF", "", self.compress, "compress", g)
        A.add("file.export_images", "Экспорт страниц в изображения", "", self.export_images, "export", g)
        A.add("file.quit", "Выход", "Ctrl+Q", self.close, None, g)
        g = "Правка"
        A.add("edit.undo", "Отменить", "Ctrl+Z", self.undo, "undo", g)
        A.add("edit.redo", "Повторить", "Ctrl+Y; Ctrl+Shift+Z", self.redo, "redo", g)
        A.add("edit.cut", "Вырезать", "Ctrl+X", lambda: self._view_call("copy", True), None, g)
        A.add("edit.copy", "Копировать", "Ctrl+C", lambda: self._view_call("copy"), None, g)
        A.add("edit.paste", "Вставить", "Ctrl+V", lambda: self._view_call("paste"), None, g)
        A.add("edit.delete", "Удалить выделенное", "Del", self.delete_selected, "trash", g)
        A.add("edit.duplicate", "Дублировать", "Ctrl+D", self.duplicate, None, g)
        A.add("edit.select_all", "Выделить всё на странице", "Ctrl+A", self.select_all, None, g)
        A.add("edit.deselect", "Снять выделение / инструмент «Выделение»", "Esc", self.escape, None, g)
        A.add("edit.add_quote", "Добавить выделенный текст в цитаты", "", self.add_selected_to_quotes, "quote", g)
        g = "Вид"
        A.add("view.zoom_in", "Увеличить", "Ctrl+=; Ctrl++", lambda: self._zoom(1), "zoom_in", g)
        A.add("view.zoom_out", "Уменьшить", "Ctrl+-", lambda: self._zoom(-1), "zoom_out", g)
        A.add("view.actual", "Реальный размер", "Ctrl+1", lambda: self._view_call("actual_size"), None, g)
        A.add("view.fit_width", "По ширине", "Ctrl+2", lambda: self._view_call("fit_width"), "fit_width", g)
        A.add("view.fit_page", "Страница целиком", "Ctrl+0", lambda: self._view_call("fit_page"), "fit_page", g)
        A.add("view.next_page", "Следующая страница", "Ctrl+PgDown", lambda: self._page_step(1), "chevron_down", g)
        A.add("view.prev_page", "Предыдущая страница", "Ctrl+PgUp", lambda: self._page_step(-1), "chevron_up", g)
        A.add("view.first_page", "Первая страница", "Ctrl+Home", lambda: self._goto(0), None, g)
        A.add("view.last_page", "Последняя страница", "Ctrl+End", lambda: self._goto(10 ** 6), None, g)
        A.add("view.goto", "Перейти к странице…", "Ctrl+Shift+N", self.goto_dialog, None, g)
        A.add("view.panel", "Показать/скрыть левую панель", "F4", lambda: self.toggle_panel(not self.panel.isVisible()), None, g)
        A.add("view.organize", "Систематизация страниц", "Ctrl+Shift+O", self.toggle_organize, "organize", g)
        A.add("view.find", "Найти в документе", "Ctrl+F", self.find, "search", g)
        A.add("view.fullscreen", "Полноэкранный режим", "Ctrl+L", self.toggle_fullscreen, None, g)
        A.add("view.floatbar_customize", "Настроить панель инструментов…", "Ctrl+Alt+T", self.customize_floatbar,
              "sliders", g)
        A.add("view.floatbar_toggle", "Показать/скрыть панель инструментов", "F8", self.toggle_floatbar, None, g)
        A.add("view.floatbar_rotate", "Повернуть панель инструментов", "Ctrl+Alt+R", self.rotate_floatbar,
              "rotate_cw", g)
        A.add("view.next_tab", "Следующий документ", "Ctrl+Tab", lambda: self._tab_step(1), None, g)
        A.add("view.prev_tab", "Предыдущий документ", "Ctrl+Shift+Tab", lambda: self._tab_step(-1), None, g)
        A.add("mode.all", "Все инструменты", "", lambda: self.set_mode("all"), "grid", g)
        A.add("mode.edit", "Редактировать PDF", "", lambda: self.set_mode("edit"), "edit_doc", g)
        A.add("mode.convert", "Преобразовать", "", lambda: self.set_mode("convert"), "convert", g)
        A.add("mode.sign", "Электронное подписание", "", lambda: self.set_mode("sign"), "sign", g)
        g = "Страницы"
        A.add("page.rotate_cw", "Повернуть страницу вправо", "Ctrl+Shift+=; Ctrl+Shift++", lambda: self.rotate_current(90), "rotate_cw", g)
        A.add("page.rotate_ccw", "Повернуть страницу влево", "Ctrl+Shift+-", lambda: self.rotate_current(-90), "rotate_ccw", g)
        A.add("page.delete", "Удалить страницу", "Ctrl+Shift+D", self.delete_current_page, "trash", g)
        A.add("page.insert_file", "Вставить страницы из файла…", "Ctrl+Shift+I", lambda: self.insert_from_file(None), "page_insert", g)
        A.add("page.insert_blank", "Вставить пустую страницу после текущей", "Ctrl+Shift+T", lambda: self.insert_blank_page(None), "page_blank", g)
        A.add("page.extract", "Извлечь страницы…", "Ctrl+Shift+E", lambda: self.extract_pages(None), "extract", g)
        A.add("org.rotate_cw", "Повернуть выделенные вправо", "", lambda: self.rotate_pages(self._org_sel(), 90), "rotate_cw", g)
        A.add("org.rotate_ccw", "Повернуть выделенные влево", "", lambda: self.rotate_pages(self._org_sel(), -90), "rotate_ccw", g)
        A.add("org.delete", "Удалить выделенные страницы", "", lambda: self.delete_pages(self._org_sel()), "trash", g)
        A.add("org.extract", "Извлечь выделенные страницы…", "", lambda: self.extract_pages(self._org_sel()), "extract", g)
        A.add("org.insert", "Вставить", "", None, "page_insert", g)
        A.add("org.replace", "Заменить", "", self.replace_pages, "pages", g)
        g = "Инструменты"
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        for key, text, default, ic in TOOLS:
            a = A.add(f"tool.{key}", text, default, (lambda k=key: self.set_tool(k)), ic, g, checkable=True)
            self.tool_group.addAction(a)
        A.add("blank.menu", "Вставить бланк", "B", self._popup_blank_menu, "blank", "Бланки")
        A.add("blank.open_dir", "Открыть папку бланков", "", self.open_blanks_dir, "folder", "Бланки")
        A.add("blank.choose_dir", "Выбрать папку бланков…", "", self.choose_blanks_dir, "folder", "Бланки")
        A.add("blank.clean_doc", "Убрать «1» в комментариях бланков (документ)", "Ctrl+Alt+1",
              self.clean_ones_current, "blank", "Бланки")
        A.add("blank.clean_folder", "Убрать «1» во всех бланках папки…", "", self.clean_ones_in_folder, "blank", "Бланки")
        A.add("quote.here", "Случайная цитата под курсором", "Shift+Q", self.quote_at_cursor, "quote", "Цитаты")
        A.add("app.quotes", "Цитаты…", "Ctrl+Alt+Q", self.edit_quotes, "quote", "Цитаты")
        g = "Текст"
        A.add("text.bold", "Полужирный", "Ctrl+B", lambda: self._toggle_fmt("bold"), "bold", g)
        A.add("text.italic", "Курсив", "Ctrl+I", lambda: self._toggle_fmt("italic"), "italic", g)
        A.add("text.bigger", "Увеличить шрифт", "Ctrl+]", lambda: self._size_step(1), None, g)
        A.add("text.smaller", "Уменьшить шрифт", "Ctrl+[", lambda: self._size_step(-1), None, g)
        A.add("text.fit", "Размер текста по странице", "Ctrl+Shift+F", lambda: self.format_changed({"fit": True}), "fit_text", g)
        A.add("text.left", "Выровнять влево", "Ctrl+Shift+L", lambda: self.format_changed({"align": "left"}), "align_left", g)
        A.add("text.center", "Выровнять по центру", "Ctrl+Shift+C", lambda: self.format_changed({"align": "center"}), "align_center", g)
        A.add("text.right", "Выровнять вправо", "Ctrl+Shift+R", lambda: self.format_changed({"align": "right"}), "align_right", g)
        for i, (name, col) in enumerate((("красный", "#ff0000"), ("чёрный", "#000000"), ("синий", "#1f4fd6"),
                                         ("зелёный", "#118a2e")), 1):
            A.add(f"color.{i}", f"Цвет: {name}", f"Alt+{i}", lambda c=col: self.format_changed({"color": c}), None, g)
        g = "Подписи"
        A.add("sign.new", "Добавить подпись…", "", lambda: self.new_signature("signature"), "sign", g)
        A.add("sign.new_initials", "Добавить инициалы…", "", lambda: self.new_signature("initials"), "sign", g)
        g = "Программа"
        A.add("app.hotkeys", "Горячие клавиши…", "Ctrl+Alt+K", self.hotkeys, "keyboard", g)
        A.add("app.settings", "Настройки…", "Ctrl+K", self.settings, "sliders", g)
        A.add("app.default_pdf", "Сделать RedColor программой для PDF", "", self.make_default, "pdf", g)
        A.add("app.about", "О программе", "", self.about, "help", g)
        A.add("app.info", "Информация (инструкция)", "F1", self.show_info, "help", g)
        # меню «Меню»
        m = self.app_menu
        for aid in ("file.new", "file.open"):
            m.addAction(A[aid])
        m.addMenu(self.recent_menu)
        m.addSeparator()
        for aid in ("file.save", "file.save_as", "file.print"):
            m.addAction(A[aid])
        m.addSeparator()
        for aid in ("file.merge", "file.compress", "file.export_images", "page.extract"):
            m.addAction(A[aid])
        m.addSeparator()
        for aid in ("app.quotes", "blank.choose_dir", "view.floatbar_customize", "app.hotkeys", "app.settings",
                    "app.default_pdf", "app.info", "app.about"):
            m.addAction(A[aid])
        m.addSeparator()
        m.addAction(A["file.close"])
        m.addAction(A["file.quit"])
        for aid in ("file.new", "file.merge", "file.open"):
            self.create_menu.addAction(A[aid])
        for menu in (self.insert_menu, self.org_insert_menu):
            menu.aboutToShow.connect(lambda menu=menu: self._fill_insert_menu(menu))
        self.sign_menu.aboutToShow.connect(self._fill_sign_menu)
        self.blank_menu.aboutToShow.connect(self._fill_blank_menu)

    # ================================================================ режимы и панели
    def set_mode(self, mode):
        if self.doc() and self.doc().in_organize() and mode != "organize":
            self.exit_organize()
        self.mode = mode
        b = self.modebar.btns.get(mode)
        if b:
            b.setChecked(True)
        self.panel.show_page(mode)
        self.toggle_panel(True)
        S["left_tab"] = ["all", "edit", "convert", "sign"].index(mode) if mode in ("all", "edit", "convert", "sign") else 1
        self._update_format_panel()

    def toggle_panel(self, vis):
        self.panel.setVisible(vis)
        S["left_panel"] = vis

    def doc(self):
        w = self.stack.currentWidget()
        return w if isinstance(w, DocumentWidget) else None

    def view(self):
        d = self.doc()
        return d.view if d else None

    def model(self):
        d = self.doc()
        return d.model if d else None

    def _view_call(self, name, *args):
        v = self.view()
        if v is not None:
            getattr(v, name)(*args)

    # ================================================================ инструменты
    def set_tool(self, key):
        self.tools.tool = key
        a = self.A.get(f"tool.{key}")
        if a is not None and not a.isChecked():
            a.setChecked(True)
        for d in self.docs:
            v = d.view
            v._update_cursor(v.viewport().rect().center())
            if key != "select":
                ed = v.editing_item()
                if ed is not None and key != "text":
                    ed.end_edit()
        if key == "signature" and not self.tools.signature_id:
            if STORE.items:
                self.tools.signature_id = STORE.items[0]["id"]
            else:
                QTimer.singleShot(0, lambda: self.new_signature("signature", arm=True))
        if key == "image":
            pass
        self._update_format_panel()

    def escape(self):
        v = self.view()
        if v is not None:
            ed = v.editing_item()
            if ed is not None:
                ed.end_edit()
                return
            if v.scene().selectedItems():
                v.scene().clearSelection()
                return
        d = self.doc()
        if d and d.findbar.isVisible():
            d.findbar.close_bar()
            return
        self.set_tool("select")

    # ================================================================ формат текста
    def _selected_text_items(self):
        v = self.view()
        if v is None:
            return []
        ed = v.editing_item()
        items = [it for it in v.scene().selectedItems() if isinstance(it, TextItem)]
        if ed is not None and ed not in items:
            items.append(ed)
        return items

    def _update_format_panel(self, *a):
        items = self._selected_text_items()
        show = bool(items) or self.tools.tool in ("text", "quote", "formula")
        self.panel.show_format(show)
        if items:
            self.panel.fmt.show_props(items[0].props(), S["text_size_auto"])
        else:
            v = self.view()
            page = None
            if v is not None and v.model.pages:
                page = v.model.pages[v.current_page()]
            self.panel.fmt.show_props(self.tools.text_props(page), S["text_size_auto"])

    def format_changed(self, kw):
        items = self._selected_text_items()
        v = self.view()
        if "auto" in kw:
            S["text_size_auto"] = kw["auto"]
        if "fit" in kw:
            kw = {"fit": True}
        for k in ("font", "color", "bold", "italic", "align"):
            if k in kw:
                S[{"font": "text_font", "color": "text_color", "bold": "text_bold", "italic": "text_italic",
                   "align": "text_align"}[k]] = kw[k]
        if "size" in kw:
            S["text_size"] = kw["size"]
            S["text_size_auto"] = False
        S.save()
        if items and v is not None:
            before = [it.state() for it in items]
            for it in items:
                if kw.get("fit"):
                    pg = it.parentItem()
                    it.set_props(size=round(pg.w * S["auto_size_pct"] / 100 * 2) / 2)
                    continue
                props = {k: kw[k] for k in ("font", "size", "color", "bold", "italic", "align") if k in kw}
                if props:
                    it.set_props(**props)
            v.model.push_state(items, before, [it.state() for it in items], "Формат текста")
        # цвет — также для выделенных фигур/рисунков/подписей
        if "color" in kw and v is not None:
            others = [it for it in v.scene().selectedItems() if isinstance(it, (InkItem, ShapeItem, ImageItem))]
            if others:
                before = [it.state() for it in others]
                for it in others:
                    it.set_color(kw["color"])
                v.model.push_state(others, before, [it.state() for it in others], "Цвет")
        self._update_format_panel()

    def _toggle_fmt(self, key):
        items = self._selected_text_items()
        cur = items[0].props()[key] if items else S["text_" + key]
        self.format_changed({key: not cur})

    def _size_step(self, d):
        items = self._selected_text_items()
        cur = items[0].size if items else self.tools.text_props(None)["size"]
        self.format_changed({"size": max(1.0, cur + d)})

    def _ink_color(self, c):
        S["ink_color"] = c
        S["shape_color"] = c
        S.save()
        v = self.view()
        if v is not None:
            items = [it for it in v.scene().selectedItems() if isinstance(it, (InkItem, ShapeItem))]
            if items:
                before = [it.state() for it in items]
                for it in items:
                    it.set_color(c)
                v.model.push_state(items, before, [it.state() for it in items], "Цвет")

    def _ink_width(self, t):
        try:
            w = float(t.replace(",", "."))
        except ValueError:
            return
        if 0.1 <= w <= 50:
            S["ink_width"] = w
            S["shape_width"] = w
            S.save()
            v = self.view()
            if v is not None:
                items = [it for it in v.scene().selectedItems() if isinstance(it, (InkItem, ShapeItem))]
                if items:
                    before = [it.state() for it in items]
                    for it in items:
                        it.width = w
                        it.prepareGeometryChange()
                        it.update()
                    v.model.push_state(items, before, [it.state() for it in items], "Толщина")

    # ================================================================ документы
    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Открыть", S.get("last_dir", ""),
                                                "PDF и изображения (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff);;Все файлы (*.*)")
        if paths:
            S["last_dir"] = str(Path(paths[0]).parent)
            self.open_paths(paths)

    def open_paths(self, paths):
        for p in paths:
            p = str(Path(p))
            for i, d in enumerate(self.docs):
                if d.model.path and Path(d.model.path) == Path(p):
                    self.title.tabs.setCurrentIndex(i)
                    break
            else:
                try:
                    model = DocModel(p)
                except Exception as e:
                    QMessageBox.warning(self, APP_NAME, f"Не удалось открыть файл:\n{p}\n\n{e}")
                    continue
                if Path(p).suffix.lower() in IMG_EXT:
                    model.path = None
                    model.title = Path(p).stem + ".pdf"
                self._add_doc(model)
                if model.path:
                    S.add_recent(p)
        self.home.refresh()

    def _add_doc(self, model):
        d = DocumentWidget(model, self)
        self.docs.append(d)
        self.stack.addWidget(d)
        i = self.title.tabs.addTab(icons.icon("pdf"), model.title)
        self.title.tabs.setTabToolTip(i, model.path or model.title)
        model.modified_changed.connect(lambda m, d=d: self._update_tab(d))
        model.path_changed.connect(lambda p, d=d: self._update_tab(d))
        d.view.selection_changed.connect(self._update_format_panel)
        d.view.status.connect(self.toast.show_msg)
        self.title.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(d)
        d.view.setFocus()
        if S.get("auto_remove_ones", True) and model.path:
            QTimer.singleShot(150, lambda d=d: self._auto_clean_ones(d))

    def _auto_clean_ones(self, d):
        if d not in self.docs:
            return
        try:
            n = d.model.remove_comment_ones()
        except Exception as e:
            print("auto ones error:", e)
            return
        if n:
            self.toast.show_msg(f"Убрано «1» в комментариях бланков: {n}  (Ctrl+Z — вернуть)", 4000)

    def clean_ones_current(self):
        m = self.model()
        if m is None:
            return
        n = m.remove_comment_ones()
        self.toast.show_msg(f"Убрано «1» в комментариях бланков: {n}" if n else "«1» в комментариях не найдено")

    def clean_ones_in_folder(self):
        files = blanks.blank_files()
        if not files:
            self.toast.show_msg("Папка бланков не выбрана или пуста")
            return
        backup = Path(S["blanks_dir"]) / "_оригиналы с единицами"
        if QMessageBox.question(self, APP_NAME, f"Убрать красные «1» из комментариев во всех бланках папки?\n\n"
                                f"Оригиналы будут сохранены в:\n{backup}") != QMessageBox.Yes:
            return
        total, failed = 0, []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in files:
                try:
                    total += blanks.clean_blank_file(p, backup)
                except Exception as e:
                    failed.append(f"{p.name}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        msg = f"Убрано «1»: {total}"
        if failed:
            QMessageBox.warning(self, APP_NAME, msg + "\n\nНе удалось обработать:\n" + "\n".join(failed))
        else:
            self.toast.show_msg(msg)

    def _update_tab(self, d):
        if d not in self.docs:
            return
        i = self.docs.index(d)
        t = d.model.title + (" •" if not d.model.undo.isClean() else "")
        self.title.tabs.setTabText(i, t)
        self.title.tabs.setTabToolTip(i, d.model.path or d.model.title)
        if d is self.doc():
            self.setWindowTitle(f"{d.model.title} — {APP_NAME}")

    def _tab_changed(self, i):
        if 0 <= i < len(self.docs):
            self.stack.setCurrentWidget(self.docs[i])
            self.setWindowTitle(f"{self.docs[i].model.title} — {APP_NAME}")
            self.docs[i].view.update_render()
        self._update_format_panel()

    def _tab_moved(self, a, b):
        self.docs.insert(b, self.docs.pop(a))

    def _tab_step(self, d):
        n = self.title.tabs.count()
        if n:
            self.title.tabs.setCurrentIndex((self.title.tabs.currentIndex() + d) % n)

    def show_home(self):
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)
        self.title.tabs.blockSignals(True)
        self.title.tabs.setCurrentIndex(-1)
        self.title.tabs.blockSignals(False)

    def _ask_save(self, d):
        if d.model.undo.isClean():
            return True
        mb = QMessageBox(self)
        mb.setWindowTitle(APP_NAME)
        mb.setText(f"Сохранить изменения в «{d.model.title}»?")
        ys = mb.addButton("Сохранить", QMessageBox.AcceptRole)
        no = mb.addButton("Не сохранять", QMessageBox.DestructiveRole)
        mb.addButton("Отмена", QMessageBox.RejectRole)
        mb.exec()
        if mb.clickedButton() == ys:
            return self._save_doc(d)
        return mb.clickedButton() == no

    def close_doc(self, i):
        if not (0 <= i < len(self.docs)):
            return
        d = self.docs[i]
        if not self._ask_save(d):
            return
        self.docs.pop(i)
        self.title.tabs.removeTab(i)
        self.stack.removeWidget(d)
        d.model.close()
        d.deleteLater()
        if not self.docs:
            self.show_home()

    def closeEvent(self, e):
        for d in list(self.docs):
            self.title.tabs.setCurrentIndex(self.docs.index(d))
            if not self._ask_save(d):
                e.ignore()
                return
        self._closing = True
        S["maximized"] = self.isMaximized()
        if not self.isMaximized():
            S["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        S.save()
        from .render import service
        service().shutdown()
        e.accept()

    # ================================================================ сохранение
    def _save_doc(self, d, path=None):
        v = d.view
        ed = v.editing_item()
        if ed is not None:
            ed.end_edit()
        if path is None:
            path = d.model.path
        if not path:
            return self._save_as_doc(d)
        from .document import FileLockedError
        while True:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                d.model.save(path)
                break
            except FileLockedError:
                QApplication.restoreOverrideCursor()
                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Warning)
                mb.setWindowTitle(APP_NAME)
                mb.setText(f"Файл «{Path(path).name}» сейчас открыт в другой программе "
                           f"(например, в Adobe Acrobat), поэтому Windows не даёт его перезаписать.")
                mb.setInformativeText("Закройте файл в той программе и нажмите «Повторить» — "
                                      "или сохраните под другим именем. Изменения не потеряются.")
                retry = mb.addButton("Повторить", QMessageBox.AcceptRole)
                save_as = mb.addButton("Сохранить как…", QMessageBox.ActionRole)
                mb.addButton("Отмена", QMessageBox.RejectRole)
                mb.exec()
                if mb.clickedButton() == retry:
                    continue
                if mb.clickedButton() == save_as:
                    return self._save_as_doc(d)
                return False
            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, APP_NAME, f"Не удалось сохранить:\n{e}")
                return False
        QApplication.restoreOverrideCursor()
        S.add_recent(path)
        self.toast.show_msg(f"Сохранено: {Path(path).name}")
        return True

    def _save_as_doc(self, d):
        start = d.model.path or str(Path(S.get("last_dir", "")) / d.model.title)
        p, _ = QFileDialog.getSaveFileName(self, "Сохранить как", start, "PDF (*.pdf)")
        if not p:
            return False
        if not p.lower().endswith(".pdf"):
            p += ".pdf"
        S["last_dir"] = str(Path(p).parent)
        return self._save_doc(d, p)

    def save(self):
        d = self.doc()
        if d:
            self._save_doc(d)

    def save_as(self):
        d = self.doc()
        if d:
            self._save_as_doc(d)

    # ================================================================ правка
    def undo(self):
        v = self.view()
        if v is None:
            return
        ed = v.editing_item()
        if ed is not None:
            ed.doc.undo()
            return
        v.model.undo.undo()
        self._update_format_panel()

    def redo(self):
        v = self.view()
        if v is None:
            return
        ed = v.editing_item()
        if ed is not None:
            ed.doc.redo()
            return
        v.model.undo.redo()

    def delete_selected(self):
        d = self.doc()
        if d is None:
            return
        if d.in_organize():
            self.delete_pages(self._org_sel())
            return
        v = d.view
        ed = v.editing_item()
        if ed is not None:
            cur = ed.ed.textCursor()
            if cur.hasSelection():
                cur.removeSelectedText()
            else:
                cur.deleteChar()
            return
        items = v.selected_boxes()
        if items:
            v.model.remove_items(items, "Удаление")

    def duplicate(self):
        v = self.view()
        if v is None:
            return
        from .items import create_item
        new = []
        for it in v.selected_boxes():
            c = create_item(it.export_state())
            if c is not None:
                c.setPos(it.pos().x() + 12, it.pos().y() + 12)
                new.append((it.parentItem(), c))
        if new:
            v.model.add_items(new, "Дублировать")
            v.scene().clearSelection()
            for _, c in new:
                c.setSelected(True)

    def select_all(self):
        d = self.doc()
        if d is None:
            return
        if d.in_organize():
            d.organize.selectAll()
            return
        v = d.view
        ed = v.editing_item()
        if ed is not None:
            c = ed.ed.textCursor()
            c.select(c.SelectionType.Document)
            ed.ed.setTextCursor(c)
            return
        pi = v.model.pages[v.current_page()]
        v.scene().clearSelection()
        for it in pi.overlay_items():
            it.setSelected(True)

    # ================================================================ вид
    def _zoom(self, d):
        v = self.view()
        if v is not None and not self.doc().in_organize():
            v.zoom_step(d)
        elif self.doc() and self.doc().in_organize():
            o = self.doc().organize
            o.set_thumb(max(70, min(400, int(o.thumb * (1.15 if d > 0 else 1 / 1.15)))))

    def _page_step(self, d):
        v = self.view()
        if v is not None:
            v.go_to_page(v.current_page() + d)

    def _goto(self, i):
        v = self.view()
        if v is not None:
            v.go_to_page(i)

    def goto_dialog(self):
        v = self.view()
        if v is None:
            return
        n, ok = QInputDialog.getInt(self, "Перейти к странице", f"Страница (1–{len(v.model.pages)}):",
                                    v.current_page() + 1, 1, len(v.model.pages))
        if ok:
            v.go_to_page(n - 1)

    def find(self):
        d = self.doc()
        if d is not None:
            d.findbar.open()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.title.show()
            self.modebar.show()
        else:
            self.title.hide()
            self.modebar.hide()
            self.showFullScreen()

    def _search_enter(self):
        t = self.modebar.search.text().strip()
        if not t:
            return
        for aid in self.A.ordered():
            if self.A.meta[aid][1].lower() == t.lower():
                self.A[aid].trigger()
                self.modebar.search.clear()
                return
        d = self.doc()
        if d is not None:
            d.findbar.open()
            d.findbar.edit.setText(t)
            d.findbar.search()
        self.modebar.search.clear()

    # ================================================================ страницы
    def _cur_index(self):
        v = self.view()
        return v.current_page() if v else 0

    def _org_sel(self):
        d = self.doc()
        if d and d.organize is not None:
            rows = d.organize.selected_indices()
            if rows:
                return rows
        return [self._cur_index()]

    def rotate_current(self, delta):
        d = self.doc()
        if d is None:
            return
        self.rotate_pages(self._org_sel() if d.in_organize() else [self._cur_index()], delta)

    def rotate_pages(self, rows, delta):
        m = self.model()
        if m is not None and rows:
            m.rotate_pages(rows, delta)

    def delete_current_page(self):
        d = self.doc()
        if d is None:
            return
        self.delete_pages(self._org_sel() if d.in_organize() else [self._cur_index()])

    def delete_pages(self, rows):
        m = self.model()
        if m is None or not rows:
            return
        if len(rows) >= len(m.pages):
            QMessageBox.information(self, APP_NAME, "Нельзя удалить все страницы документа.")
            return
        m.delete_pages(rows)
        self.toast.show_msg(f"Удалено страниц: {len(rows)} (Ctrl+Z — вернуть)")

    def extract_pages(self, rows):
        m = self.model()
        if m is None:
            return
        if rows is None:
            d = self.doc()
            rows = self._org_sel() if d.in_organize() else None
        if rows is None:
            text, ok = QInputDialog.getText(self, "Извлечь страницы",
                                            f"Номера страниц (например 1-3, 5), всего {len(m.pages)}:",
                                            text=str(self._cur_index() + 1))
            if not ok:
                return
            rows = parse_ranges(text, len(m.pages))
        if not rows:
            return
        stem = Path(m.title).stem
        p, _ = QFileDialog.getSaveFileName(self, "Сохранить страницы", str(Path(S.get("last_dir", "")) / f"{stem}_стр.pdf"),
                                           "PDF (*.pdf)")
        if p:
            m.extract_pages(rows, p)
            self.toast.show_msg(f"Извлечено страниц: {len(rows)}")

    def insert_from_file(self, at):
        m = self.model()
        if m is None:
            return
        if at is None:
            at = self._cur_index() + 1
        p, _ = QFileDialog.getOpenFileName(self, "Вставить страницы", S.get("last_dir", ""),
                                           "PDF и изображения (*.pdf *.png *.jpg *.jpeg)")
        if p:
            m.insert_file(p, at)
            QTimer.singleShot(50, lambda: self.view().go_to_page(at))

    def insert_blank_page(self, at):
        m = self.model()
        if m is None:
            return
        if at is None:
            at = self._cur_index() + 1
        m.insert_blank_page(at)
        if not self.doc().in_organize():
            QTimer.singleShot(50, lambda: self.view().go_to_page(at))

    def replace_pages(self):
        m = self.model()
        if m is None:
            return
        rows = self._org_sel()
        p, _ = QFileDialog.getOpenFileName(self, "Заменить страницы", S.get("last_dir", ""), "PDF (*.pdf)")
        if not p:
            return
        import pymupdf
        src = pymupdf.open(p)
        n = min(len(rows), src.page_count)
        sub = pymupdf.open()
        sub.insert_pdf(src, from_page=0, to_page=n - 1)
        m.undo.beginMacro("Заменить страницы")
        at = rows[0]
        m.insert_pdf(sub, at)
        m.delete_pages([r + n if r >= at else r for r in rows[:n]])
        m.undo.endMacro()

    def _fill_insert_menu(self, menu):
        menu.clear()
        d = self.doc()
        if d is None:
            return
        at = (self._org_sel()[-1] + 1) if d.in_organize() else self._cur_index() + 1
        menu.addAction(icons.icon("page_insert"), "Из файла…", lambda: self.insert_from_file(at))
        menu.addAction(icons.icon("page_blank"), "Пустая страница", lambda: self.insert_blank_page(at))
        bm = menu.addMenu(icons.icon("blank"), "Бланк")
        self.fill_blank_menu(bm, at)

    def toggle_organize(self):
        d = self.doc()
        if d is None:
            return
        if d.in_organize():
            self.exit_organize()
        else:
            d.enter_organize()
            self.panel.show_page("organize")
            self.toggle_panel(True)

    def exit_organize(self):
        d = self.doc()
        if d is not None and d.in_organize():
            d.exit_organize()
        self.panel.show_page(self.mode if self.mode in ("all", "edit", "convert", "sign") else "edit")

    def organize_select(self, i):
        d = self.doc()
        if d is None or d.organize is None:
            return
        o = d.organize
        o.clearSelection()
        for r in range(o.count()):
            p = d.model.pages[r]
            ok = {1: True, 2: (r + 1) % 2 == 0, 3: (r + 1) % 2 == 1, 4: p.h >= p.w, 5: p.w > p.h}.get(i, False)
            o.item(r).setSelected(ok)

    def organize_thumb_size(self, s):
        d = self.doc()
        if d is not None and d.organize is not None:
            d.organize.set_thumb(s)

    # ================================================================ бланки и цитаты
    @staticmethod
    def _blank_aid(p):
        d = Path(S.get("blanks_dir") or "")
        try:
            rel = str(p.relative_to(d))
        except ValueError:
            rel = p.name
        return "blank.file." + rel.replace("\\", "/")

    def rebuild_blank_actions(self):
        for aid in [a for a in self.A.ordered() if a.startswith("blank.file.")]:
            self.A.remove(aid)
        files = blanks.blank_files()
        for p in files:
            self.A.add(self._blank_aid(p), f"Бланк: {blanks.blank_label(p)}", "", lambda p=p: self.insert_blank(p),
                       "blank", "Бланки")
        self._watch_blanks()
        if hasattr(self, "panel"):
            self.panel.refresh_blanks(files)

    def _watch_blanks(self):
        from PySide6.QtCore import QFileSystemWatcher
        if not hasattr(self, "_blank_watch"):
            self._blank_watch = QFileSystemWatcher(self)
            self._blank_timer = QTimer(self)
            self._blank_timer.setSingleShot(True)
            self._blank_timer.setInterval(600)
            self._blank_timer.timeout.connect(self.rebuild_blank_actions)
            self._blank_watch.directoryChanged.connect(lambda *_: self._blank_timer.start())
        old = self._blank_watch.directories()
        if old:
            self._blank_watch.removePaths(old)
        d = Path(S.get("blanks_dir") or "")
        if str(S.get("blanks_dir") or "").strip() and d.is_dir():
            dirs = [str(d)] + [str(x) for x in d.rglob("*") if x.is_dir() and not x.name.startswith(("_", "."))]
            self._blank_watch.addPaths(dirs[:200])

    def choose_blanks_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с бланками", S.get("blanks_dir") or S.get("last_dir", ""))
        if d:
            S["blanks_dir"] = d
            S.save()
            self.rebuild_blank_actions()
            n = len(blanks.blank_files())
            self.toast.show_msg(f"Папка бланков: {Path(d).name} — найдено бланков: {n}")

    def _fill_blank_menu(self):
        self.fill_blank_menu(self.blank_menu, None)

    def fill_blank_menu(self, menu, at):
        menu.clear()
        files = blanks.blank_files()
        if not files:
            msg = "Папка бланков не выбрана" if not S.get("blanks_dir") else "В папке нет PDF-бланков"
            a = menu.addAction(msg)
            a.setEnabled(False)
        groups = {}
        for p in files:
            label = blanks.blank_label(p)
            parent, _, name = label.rpartition(" / ")
            target = menu
            if parent:
                if parent not in groups:
                    groups[parent] = menu.addMenu(icons.icon("folder"), parent)
                target = groups[parent]
            sc = self.A.label(self._blank_aid(p)) if self.A.get(self._blank_aid(p)) else ""
            act = target.addAction(icons.icon("blank"), (name or label) + (f"\t{sc}" if sc else ""))
            act.triggered.connect(lambda _=False, p=p: self.insert_blank(p, at))
        menu.addSeparator()
        auto = menu.addAction("Случайная цитата при вставке")
        auto.setCheckable(True)
        auto.setChecked(S["auto_quote_on_blank"])
        auto.toggled.connect(lambda b: (S.__setitem__("auto_quote_on_blank", b), S.save()))
        menu.addAction(self.A["app.quotes"])
        menu.addSeparator()
        menu.addAction(self.A["blank.choose_dir"])
        menu.addAction(self.A["blank.open_dir"])
        menu.addAction(self.A["blank.clean_doc"])
        menu.addAction(self.A["blank.clean_folder"])

    def _popup_blank_menu(self):
        self._fill_blank_menu()
        self.blank_menu.exec(QCursor.pos())

    def insert_blank(self, path, at=None):
        d = self.doc()
        if d is None:
            self.toast.show_msg("Сначала откройте документ")
            return
        m = d.model
        if at is None:
            at = (self._org_sel()[-1] + 1) if d.in_organize() else d.view.current_page() + 1
        try:
            src = blanks.prepared_blank(path)
            info = blanks.analyze(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Не удалось открыть бланк:\n{e}")
            return
        m.undo.beginMacro(f"Бланк {Path(path).stem}")
        new_pages = m.insert_pdf(src, at, f"Бланк {Path(path).stem}")
        if S["auto_quote_on_blank"] and new_pages:
            q = blanks.QUOTES.next()
            if q:
                x, y, w, size, mh = blanks.quote_placement(info)
                pi = new_pages[0]
                props = {"font": fonts.resolve(S["quote_font"]), "size": size, "color": S["text_color"],
                         "bold": False, "italic": False, "align": "left"}
                it = self._make_fitted_text(props, w, q, mh)
                it.setPos(x, y)
                m.add_items([(pi, it)], "Цитата")
        m.undo.endMacro()
        if not d.in_organize():
            QTimer.singleShot(60, lambda: d.view.go_to_page(at))
        self.toast.show_msg(f"Вставлен бланк «{Path(path).stem}»")

    def _make_fitted_text(self, props, width, text, max_h):
        it = TextItem(props, width)
        it.set_runs(((None, (("t", text),)),))
        while it.size_h() > max_h and it.size > 6:
            it.set_props(size=it.size - 0.5)
        return it

    def place_quote(self, view, pi, pos):
        q = blanks.QUOTES.next()
        if not q:
            self.toast.show_msg("Список цитат пуст — добавьте цитаты (Меню → Цитаты…)")
            return
        it = view.create_text(pi, pos, ((None, (("t", q),)),), start_edit=False)
        self.tools.after_place()

    def quote_at_cursor(self):
        v = self.view()
        if v is None:
            return
        pi, pos = v._paste_target()
        if pi is not None:
            self.place_quote(v, pi, pos)

    def edit_quotes(self):
        QuotesDialog(blanks.QUOTES, self).exec()

    def add_selected_to_quotes(self):
        items = self._selected_text_items()
        texts = []
        for it in items:
            if it.editing and it.ed.textCursor().hasSelection():
                texts.append(it.ed.textCursor().selectedText().replace(" ", " "))
            else:
                texts.append(it.plain_text().replace("\n", " "))
        texts = [t.strip() for t in texts if t.strip()]
        if not texts:
            self.toast.show_msg("Выделите текстовый блок")
            return
        allq = blanks.QUOTES.quotes + [t for t in texts if t not in blanks.QUOTES.quotes]
        blanks.QUOTES.save("\n".join(allq))
        self.toast.show_msg(f"Добавлено в цитаты: {len(texts)}")

    # ================================================================ подписи
    def rebuild_signature_actions(self):
        for aid in [a for a in self.A.ordered() if a.startswith("sign.item.")]:
            self.A.remove(aid)
        for x in STORE.items:
            self.A.add(f"sign.item.{x['id']}", f"Подпись: {x['name']}", "",
                       lambda sid=x["id"]: self.arm_signature(sid), "sign", "Подписи")

    def _fill_sign_menu(self):
        m = self.sign_menu
        m.clear()
        from .signatures import thumb
        col = S.get("signature_color") or S["text_color"]
        for x in STORE.items:
            a = m.addAction(QIcon(thumb(x["id"], col)), x["name"])
            a.triggered.connect(lambda _=False, sid=x["id"]: self.arm_signature(sid))
        if STORE.items:
            m.addSeparator()
        m.addAction(self.A["sign.new"])
        m.addAction(self.A["sign.new_initials"])

    def signatures_changed(self):
        self.panel.refresh_signatures()
        self.rebuild_signature_actions()

    def new_signature(self, kind, arm=True):
        dlg = SignatureDialog(kind, self)
        if dlg.exec() and dlg.sid:
            self.signatures_changed()
            if arm:
                self.arm_signature(dlg.sid)
        elif self.tools.tool == "signature" and not STORE.items:
            self.set_tool("select")

    def arm_signature(self, sid):
        self.tools.signature_id = sid
        self.set_tool("signature")
        self.toast.show_msg("Щёлкните на странице, чтобы поставить подпись")

    def rename_signature(self, sid):
        x = STORE.get(sid)
        if not x:
            return
        name, ok = QInputDialog.getText(self, "Подпись", "Название:", text=x["name"])
        if ok and name.strip():
            STORE.rename(sid, name.strip())
            self.signatures_changed()

    def delete_signature(self, sid):
        if QMessageBox.question(self, "Подпись", "Удалить подпись из списка?") == QMessageBox.Yes:
            STORE.remove(sid)
            if self.tools.signature_id == sid:
                self.tools.signature_id = None
            self.signatures_changed()

    def place_signature(self, view, pi, pos):
        sid = self.tools.signature_id or (STORE.items[0]["id"] if STORE.items else None)
        if not sid:
            self.new_signature("signature")
            return
        data = STORE.data(sid)
        x = STORE.get(sid)
        img = QImage.fromData(data)
        w = pi.w * (0.09 if x and x.get("kind") == "initials" else 0.2)
        view.insert_image_data(pi, pos, data, img.width(), img.height(), signature=True,
                               tint=S.get("signature_color") or S["text_color"], width=w)
        self.tools.after_place()

    # ================================================================ изображения и формулы
    def place_image(self, view, pi, pos):
        p, _ = QFileDialog.getOpenFileName(self, "Изображение", S.get("last_dir", ""),
                                           "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if p:
            img = QImage(p)
            if not img.isNull():
                view.insert_image_data(pi, pos, Path(p).read_bytes(), img.width(), img.height())
        self.tools.after_place()

    def place_formula(self, view, pi, pos):
        dlg = FormulaDialog("", "", self)
        if dlg.exec() and dlg.result is not None:
            view.create_text(pi, pos, ((None, (("f", dlg.result.key, False),)),), start_edit=False)
        self.tools.after_place()

    def edit_formula(self, view, item, pos):
        key = item.formula_at(pos)
        f = REGISTRY.get(key)
        if f is None:
            return
        latex = f.latex
        hint = ""
        if not latex:
            try:
                from .svg2tex import svg_to_latex
                latex = svg_to_latex(f.svg)
                hint = "Формула вставлена с сайта картинкой. LaTeX восстановлен автоматически — проверьте и поправьте."
            except Exception:
                latex = ""
                hint = "Не удалось восстановить LaTeX — введите формулу заново."
        dlg = FormulaDialog(latex, hint, self)
        if dlg.exec() and dlg.result is not None:
            before = item.state()
            item.replace_formula(pos, dlg.result)
            view.model.push_state([item], [before], [item.state()], "Формула")

    # ================================================================ файлы
    def new_blank_pdf(self):
        import pymupdf
        d = pymupdf.open()
        d.new_page(width=595.28, height=841.89)
        model = DocModel(data=d.tobytes(), title="Новый документ.pdf")
        model.path = None
        self._add_doc(model)

    def merge_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Объединение файлов", S.get("last_dir", ""),
                                                "PDF и изображения (*.pdf *.png *.jpg *.jpeg)")
        if not paths:
            return
        m = self.model()
        if m is None:
            import pymupdf
            out = pymupdf.open()
            for p in paths:
                if Path(p).suffix.lower() in IMG_EXT:
                    img = pymupdf.open(p)
                    out.insert_pdf(pymupdf.open("pdf", img.convert_to_pdf()))
                else:
                    out.insert_pdf(pymupdf.open(p))
            model = DocModel(data=out.tobytes(), title="Объединённый.pdf")
            model.path = None
            self._add_doc(model)
            return
        m.undo.beginMacro("Объединение файлов")
        for p in paths:
            m.insert_file(p, len(m.pages))
        m.undo.endMacro()
        self.toast.show_msg(f"Добавлено файлов: {len(paths)}")

    def compress(self):
        m = self.model()
        if m is None:
            return
        stem = Path(m.title).stem
        p, _ = QFileDialog.getSaveFileName(self, "Сжать PDF", str(Path(m.path or S.get("last_dir", "")).with_name(f"{stem}_сжатый.pdf")),
                                           "PDF (*.pdf)")
        if not p:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = m.build_output(editable=False)
            out.rewrite_images(dpi_threshold=150, dpi_target=120, quality=75)
            out.save(p, garbage=4, deflate=True, clean=True)
            out.close()
            size = Path(p).stat().st_size / 1024 / 1024
        finally:
            QApplication.restoreOverrideCursor()
        self.toast.show_msg(f"Сжато: {Path(p).name} — {size:.1f} МБ")

    def export_images(self):
        m = self.model()
        if m is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Папка для изображений", S.get("last_dir", ""))
        if not folder:
            return
        dpi, ok = QInputDialog.getInt(self, "Экспорт", "Разрешение (dpi):", 150, 50, 600)
        if not ok:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = m.build_output(editable=False)
            stem = Path(m.title).stem
            for i, pg in enumerate(out):
                pg.get_pixmap(dpi=dpi).save(str(Path(folder) / f"{stem}_{i + 1:03d}.png"))
            out.close()
        finally:
            QApplication.restoreOverrideCursor()
        self.toast.show_msg(f"Сохранено изображений: {len(m.pages)}")

    def print_doc(self):
        m = self.model()
        if m is None:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        from PySide6.QtGui import QPainter
        pr = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(pr, self)
        dlg.setMinMax(1, len(m.pages))
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = m.build_output(editable=False)
            first = max(pr.fromPage(), 1) - 1 if pr.fromPage() else 0
            last = (pr.toPage() or len(m.pages)) - 1
            p = QPainter(pr)
            for i in range(first, last + 1):
                if i > first:
                    pr.newPage()
                pix = out[i].get_pixmap(dpi=300)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                r = p.viewport()
                sz = img.size()
                sz.scale(r.size(), Qt.KeepAspectRatio)
                p.setViewport(r.x(), r.y(), sz.width(), sz.height())
                p.setWindow(img.rect())
                p.drawImage(0, 0, img)
                p.setViewport(r)
            p.end()
            out.close()
        finally:
            QApplication.restoreOverrideCursor()

    # ================================================================ настройки
    def hotkeys(self):
        HotkeysDialog(self.A, self).exec()

    def settings(self):
        SettingsDialog(self, self).exec()

    def settings_applied(self, theme_changed):
        blanks.QUOTES.reload()
        self.rebuild_blank_actions()
        self._update_format_panel()
        if theme_changed:
            QMessageBox.information(self, APP_NAME, "Тема полностью применится после перезапуска программы.")

    # ================================================================ плавающая панель инструментов
    def floatbar_changed(self, rebuild=True, source=None):
        for d in self.docs:
            if d.floatbar is source:
                continue
            if rebuild:
                d.floatbar.rebuild()
            else:
                d.floatbar.place()

    def floatbar_set(self, **kw):
        from .toolbar import config, save_config
        c = config()
        c.update(kw)
        if kw.get("dock") in ("top", "bottom"):
            c["orient"] = "h"
        elif kw.get("dock") in ("left", "right"):
            c["orient"] = "v"
        save_config(c)
        self.floatbar_changed()
        if kw.get("visible") is False:
            self.toast.show_msg("Панель инструментов скрыта. Показать — F8")

    def customize_floatbar(self):
        from .toolbar import ToolbarEditor
        ToolbarEditor(self).exec()

    def reset_floatbar(self):
        import copy
        from .toolbar import DEFAULT, save_config
        save_config(copy.deepcopy(DEFAULT))
        self.floatbar_changed()

    def toggle_floatbar(self):
        from .toolbar import config
        self.floatbar_set(visible=not config().get("visible", True))

    def rotate_floatbar(self):
        from .toolbar import config
        self.floatbar_set(orient="h" if config()["orient"] == "v" else "v")

    def open_blanks_dir(self):
        d = S.get("blanks_dir") or ""
        if d and Path(d).is_dir():
            os.startfile(d)
        else:
            self.choose_blanks_dir()

    def show_info(self):
        from .dialogs import InfoDialog
        InfoDialog(self).exec()

    def about(self):
        from .config import APP_VERSION, AUTHOR, COPYRIGHT, DATA_DIR
        mb = QMessageBox(self)
        mb.setWindowTitle("О программе")
        mb.setIconPixmap(QIcon(str(ASSETS / "redcolor_256.png")).pixmap(72, 72))
        mb.setText(f"<b style='font-size:16px'>RedColor {APP_VERSION}</b><br>Редактор PDF для проверки работ")
        mb.setInformativeText(f"Автор: {AUTHOR}<br>{COPYRIGHT}<br><br>"
                              f"Данные пользователя (цитаты, подписи, настройки):<br>{DATA_DIR}")
        mb.exec()

    def make_default(self):
        from . import winreg_assoc
        try:
            winreg_assoc.register()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Не удалось зарегистрировать программу:\n{e}")
            return
        winreg_assoc.open_default_apps()
        QMessageBox.information(self, APP_NAME, "RedColor зарегистрирован как программа для PDF.\n\n"
                                "В открывшемся окне Windows «Приложения по умолчанию» → RedColor нажмите "
                                "«Установить по умолчанию» (Windows разрешает это сделать только вам).")

    # ================================================================ перетаскивание в окно
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.open_paths(paths)
            e.acceptProposedAction()

    def _fill_recent(self):
        self.recent_menu.clear()
        for p in S.get("recent", []):
            self.recent_menu.addAction(icons.icon("pdf"), Path(p).name, lambda p=p: self.open_paths([p]))


def parse_ranges(text, n):
    out = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a or 1), int(b or n)
            except ValueError:
                continue
            out.extend(range(max(a, 1) - 1, min(b, n)))
        else:
            try:
                k = int(part)
            except ValueError:
                continue
            if 1 <= k <= n:
                out.append(k - 1)
    return sorted(set(out))
