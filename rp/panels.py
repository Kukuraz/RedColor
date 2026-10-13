# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Левая панель в стиле Acrobat: Все инструменты / Редактировать / Преобразовать / Подписание / Систематизация."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import fonts, icons
from .config import S
from .signatures import STORE, thumb
from .theme import T
from .widgets import ColorButton, FlatCombo, Header, IconButton, PanelRow, section, separator

SIZES = ["6", "7", "8", "9", "10", "11", "12", "13", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72"]


def _scroll(inner):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    inner.setObjectName("scrollinner")
    sa.setWidget(inner)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return sa


class Page(QWidget):
    def __init__(self, title, panel, back=False):
        super().__init__()
        self.panel = panel
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = Header(title, back)
        self.header.closed.connect(panel.close_requested.emit)
        v.addWidget(self.header)
        self.inner = QWidget()
        self.body = QVBoxLayout(self.inner)
        self.body.setContentsMargins(12, 4, 12, 12)
        self.body.setSpacing(2)
        v.addWidget(_scroll(self.inner), 1)

    def sec(self, text, top=10):
        self.body.addSpacing(top)
        l = section(text)
        l.setContentsMargins(4, 0, 0, 6)
        self.body.addWidget(l)

    def row(self, action, submenu=None):
        b = PanelRow(action.property("icon_name") or "more", action.text(), action=action, submenu=submenu is not None)
        if submenu is not None:
            b.setMenu(submenu)
            b.setPopupMode(PanelRow.InstantPopup)
        self.body.addWidget(b)
        return b

    def icons_row(self, actions):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        out = []
        for a, menu in actions:
            b = IconButton(a.property("icon_name") or "more", a.toolTip(), 20, action=a)
            b.setIcon(a.icon())
            b.setFixedSize(34, 32)
            if menu is not None:
                b.setMenu(menu)
                b.setPopupMode(IconButton.InstantPopup)
            h.addWidget(b)
            out.append(b)
        h.addStretch(1)
        self.body.addWidget(w)
        return out


class FormatSection(QWidget):
    """«Форматировать текст» — как в Acrobat: шрифт, размер, цвет, выравнивание, начертание."""
    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addSpacing(8)
        l = section("Форматировать текст")
        l.setContentsMargins(4, 0, 0, 4)
        v.addWidget(l)
        self.font = FlatCombo()
        fav, rest = fonts.families()
        self.font.addItems(fav)
        self.font.insertSeparator(len(fav))
        self.font.addItems(rest)
        self.font.setMaxVisibleItems(22)
        v.addWidget(self.font)
        r = QHBoxLayout()
        r.setSpacing(4)
        self.size = FlatCombo()
        self.size.setEditable(True)
        self.size.addItems(SIZES)
        self.size.setFixedWidth(62)
        r.addWidget(self.size)
        self.color = ColorButton(S["text_color"])
        r.addWidget(self.color)
        r.addStretch(1)
        self.align_grp = QButtonGroup(self)
        self.align_btns = {}
        for name, ic in (("left", "align_left"), ("center", "align_center"), ("right", "align_right")):
            b = IconButton(ic, {"left": "По левому краю", "center": "По центру", "right": "По правому краю"}[name], 18)
            b.setCheckable(True)
            b.setFixedSize(28, 28)
            self.align_grp.addButton(b)
            self.align_btns[name] = b
            r.addWidget(b)
            b.clicked.connect(lambda _=False, n=name: self._emit(align=n))
        v.addLayout(r)
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.bold = IconButton("bold", "Полужирный", 18)
        self.bold.setCheckable(True)
        self.italic = IconButton("italic", "Курсив", 18)
        self.italic.setCheckable(True)
        for b in (self.bold, self.italic):
            b.setFixedSize(30, 28)
            r2.addWidget(b)
        self.fit = IconButton("fit_text", "Подогнать размер под страницу", 18)
        self.fit.setFixedSize(30, 28)
        r2.addWidget(self.fit)
        r2.addStretch(1)
        v.addLayout(r2)
        self.auto = QCheckBox("Авторазмер по странице")
        v.addWidget(self.auto)
        self._block = False
        self.font.currentTextChanged.connect(lambda t: self._emit(font=t))
        self.size.currentTextChanged.connect(self._size_changed)
        self.color.color_changed.connect(lambda c: self._emit(color=c))
        self.bold.toggled.connect(lambda b: self._emit(bold=b))
        self.italic.toggled.connect(lambda b: self._emit(italic=b))
        self.auto.toggled.connect(lambda b: self._emit(auto=b))
        self.fit.clicked.connect(lambda: self._emit(fit=True))

    def _size_changed(self, t):
        try:
            v = float(t.replace(",", "."))
        except ValueError:
            return
        if 1 <= v <= 400:
            self._emit(size=v)

    def _emit(self, **kw):
        if not self._block:
            self.changed.emit(kw)

    def show_props(self, props, auto):
        self._block = True
        self.font.setCurrentText(fonts.resolve(props.get("font", "")))
        sz = props.get("size", 12)
        self.size.setCurrentText(f"{sz:g}" if abs(sz - round(sz)) > 0.05 else str(int(round(sz))))
        self.color.set_color(props.get("color", "#ff0000"))
        self.bold.setChecked(bool(props.get("bold")))
        self.italic.setChecked(bool(props.get("italic")))
        b = self.align_btns.get(props.get("align", "left"))
        if b:
            b.setChecked(True)
        self.auto.setChecked(auto)
        self._block = False


class LeftPanel(QFrame):
    close_requested = Signal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("leftpanel")
        self.setFixedWidth(272)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        A = main.A
        # ---------------- Все инструменты
        p0 = Page("Все инструменты", self)
        p0.sec("Редактирование", 4)
        for aid in ("mode.edit", "view.organize", "tool.text", "tool.image", "tool.quote", "tool.formula"):
            p0.row(A[aid])
        p0.row(A["blank.menu"], main.blank_menu)
        p0.sec("Рисование и отметки")
        for aid in ("tool.pencil", "tool.highlighter", "tool.ellipse_num", "tool.arrow", "tool.check"):
            p0.row(A[aid])
        p0.sec("Подписание")
        p0.row(A["mode.sign"])
        p0.row(A["sign.new"])
        p0.sec("Файл")
        for aid in ("file.merge", "file.compress", "file.export_images", "app.quotes", "app.hotkeys", "app.settings"):
            p0.row(A[aid])
        p0.body.addStretch(1)
        self.stack.addWidget(p0)
        # ---------------- Редактировать
        p1 = Page("Редактировать", self)
        self.fmt = FormatSection()
        p1.body.addWidget(self.fmt)
        self.fmt_sep = separator()
        p1.body.addSpacing(8)
        p1.body.addWidget(self.fmt_sep)
        p1.sec("Изменить страницу")
        p1.icons_row([(A["page.rotate_cw"], None), (A["page.insert_file"], main.insert_menu),
                      (A["page.delete"], None), (A["page.extract"], None)])
        p1.row(A["view.organize"])
        p1.sec("Добавить содержимое", 14)
        p1.row(A["tool.text"])
        p1.row(A["tool.image"])
        p1.row(A["blank.menu"], main.blank_menu)
        p1.row(A["tool.quote"])
        p1.row(A["tool.formula"])
        p1.row(A["tool.signature"], main.sign_menu)
        p1.sec("Бланки", 14)
        self.blank_dir_btn = PanelRow("folder", "Выбрать папку…")
        self.blank_dir_btn.clicked.connect(main.choose_blanks_dir)
        p1.body.addWidget(self.blank_dir_btn)
        self.blanks_box = QWidget()
        self.blanks_lay = QVBoxLayout(self.blanks_box)
        self.blanks_lay.setContentsMargins(0, 0, 0, 0)
        self.blanks_lay.setSpacing(0)
        p1.body.addWidget(self.blanks_box)
        p1.sec("Отметки и рисование", 14)
        grid = QWidget()
        g = QGridLayout(grid)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(4)
        for i, aid in enumerate(("tool.pencil", "tool.highlighter", "tool.eraser", "tool.ellipse", "tool.ellipse_num",
                                 "tool.rect", "tool.line", "tool.arrow", "tool.check", "tool.cross", "tool.plus",
                                 "tool.minus", "tool.dot", "tool.hand")):
            b = IconButton(A[aid].property("icon_name"), A[aid].toolTip(), 18, action=A[aid])
            b.setIcon(A[aid].icon())
            b.setFixedSize(32, 30)
            g.addWidget(b, i // 6, i % 6)
        p1.body.addWidget(grid)
        draw_row = QHBoxLayout()
        draw_row.setSpacing(6)
        lab = QLabel("Линии:")
        lab.setStyleSheet(f"color:{T['text2']}")
        draw_row.addWidget(lab)
        self.ink_color = ColorButton(S["ink_color"])
        self.ink_color.setToolTip("Цвет карандаша и фигур")
        draw_row.addWidget(self.ink_color)
        self.ink_width = FlatCombo()
        self.ink_width.setEditable(True)
        self.ink_width.addItems(["0.5", "0.75", "1", "1.5", "2", "3", "4", "6"])
        self.ink_width.setCurrentText(f"{S['ink_width']:g}")
        self.ink_width.setFixedWidth(56)
        self.ink_width.setToolTip("Толщина линий, pt")
        draw_row.addWidget(self.ink_width)
        draw_row.addWidget(QLabel("pt"))
        draw_row.addStretch(1)
        p1.body.addSpacing(6)
        p1.body.addLayout(draw_row)
        p1.sec("Другие параметры", 14)
        p1.row(A["file.merge"])
        p1.row(A["app.quotes"])
        p1.row(A["app.hotkeys"])
        p1.body.addStretch(1)
        self.stack.addWidget(p1)
        # ---------------- Преобразовать
        p2 = Page("Преобразовать", self)
        p2.sec("Экспорт", 4)
        p2.row(A["file.export_images"])
        p2.row(A["page.extract"])
        p2.row(A["file.save_as"])
        p2.sec("Оптимизация")
        p2.row(A["file.compress"])
        p2.row(A["file.merge"])
        p2.body.addStretch(1)
        self.stack.addWidget(p2)
        # ---------------- Подписание
        p3 = Page("Электронное подписание", self)
        p3.sec("Ваши подписи", 4)
        self.sig_list = QListWidget()
        self.sig_list.setIconSize(QSize(180, 44))
        self.sig_list.setMinimumHeight(220)
        self.sig_list.itemClicked.connect(lambda it: main.arm_signature(it.data(Qt.UserRole)))
        self.sig_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sig_list.customContextMenuRequested.connect(self._sig_menu)
        p3.body.addWidget(self.sig_list)
        p3.row(A["sign.new"])
        p3.row(A["sign.new_initials"])
        cr = QHBoxLayout()
        cr.addWidget(QLabel("Цвет подписи"))
        self.sig_color = ColorButton(S.get("signature_color") or S["text_color"])
        self.sig_color.color_changed.connect(self._sig_color)
        cr.addWidget(self.sig_color)
        cr.addStretch(1)
        p3.body.addSpacing(8)
        p3.body.addLayout(cr)
        hint = QLabel("Щёлкните подпись, затем место на странице. Правый щелчок — переименовать или удалить.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{T['text3']};font-size:12px")
        p3.body.addSpacing(8)
        p3.body.addWidget(hint)
        p3.body.addStretch(1)
        self.stack.addWidget(p3)
        # ---------------- Систематизация
        p4 = Page("Систематизация страниц", self, back=True)
        p4.header.back.connect(main.exit_organize)
        p4.header.closed.disconnect()
        p4.header.closed.connect(main.exit_organize)
        p4.sec("Выделенные страницы", 4)
        self.sel_combo = FlatCombo()
        self.sel_combo.addItems(["", "Все страницы", "Чётные страницы", "Нечётные страницы", "Книжные", "Альбомные"])
        self.sel_combo.activated.connect(lambda i: main.organize_select(i))
        p4.body.addWidget(self.sel_combo)
        p4.sec("Параметры страницы", 16)
        p4.icons_row([(A["org.rotate_ccw"], None), (A["org.rotate_cw"], None), (A["org.delete"], None),
                      (A["org.extract"], None)])
        p4.row(A["org.insert"], main.org_insert_menu)
        p4.row(A["org.replace"])
        p4.body.addSpacing(16)
        sz = QHBoxLayout()
        sz.addWidget(QLabel("Размер миниатюр"))
        self.thumb_slider = QSlider(Qt.Horizontal)
        self.thumb_slider.setRange(70, 400)
        self.thumb_slider.setValue(150)
        self.thumb_slider.valueChanged.connect(main.organize_thumb_size)
        sz.addWidget(self.thumb_slider, 1)
        p4.body.addLayout(sz)
        p4.body.addStretch(1)
        self.stack.addWidget(p4)
        self.pages = {"all": p0, "edit": p1, "convert": p2, "sign": p3, "organize": p4}
        self.refresh_signatures()

    def show_page(self, name):
        self.stack.setCurrentWidget(self.pages[name])

    def current(self):
        for k, v in self.pages.items():
            if v is self.stack.currentWidget():
                return k
        return "edit"

    def show_format(self, visible):
        self.fmt.setVisible(visible)
        self.fmt_sep.setVisible(visible)

    def refresh_blanks(self, files):
        from pathlib import Path
        from .blanks import blank_label
        while self.blanks_lay.count():
            w = self.blanks_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        d = S.get("blanks_dir") or ""
        if d and Path(d).is_dir():
            self.blank_dir_btn.setText(f"Папка: {Path(d).name}")
            self.blank_dir_btn.setToolTip(f"{d}\nЩёлкните, чтобы выбрать другую папку")
        else:
            self.blank_dir_btn.setText("Выбрать папку с бланками…")
            self.blank_dir_btn.setToolTip("Бланки подтягиваются из выбранной папки (и её подпапок)")
        for p in files:
            b = PanelRow("blank", blank_label(p))
            b.setMinimumHeight(26)
            b.setStyleSheet("QToolButton#panelrow{padding:3px 8px;font-size:12px;}")
            b.setToolTip(f"Вставить после текущей страницы\n{p}")
            b.clicked.connect(lambda _=False, p=p: self.main.insert_blank(p))
            self.blanks_lay.addWidget(b)
        if d and Path(d).is_dir() and not files:
            l = QLabel("В папке нет PDF")
            l.setStyleSheet(f"color:{T['text3']};padding-left:10px")
            self.blanks_lay.addWidget(l)

    def refresh_signatures(self):
        self.sig_list.clear()
        col = S.get("signature_color") or S["text_color"]
        for x in STORE.items:
            it = QListWidgetItem(QIcon(thumb(x["id"], col)), x["name"])
            it.setData(Qt.UserRole, x["id"])
            it.setSizeHint(QSize(220, 54))
            self.sig_list.addItem(it)

    def _sig_color(self, c):
        S["signature_color"] = c
        S.save()
        self.refresh_signatures()
        self.main.signatures_changed()

    def _sig_menu(self, pos):
        it = self.sig_list.itemAt(pos)
        if it is None:
            return
        sid = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Поставить на страницу", lambda: self.main.arm_signature(sid))
        m.addAction("Переименовать…", lambda: self.main.rename_signature(sid))
        m.addAction("Удалить", lambda: self.main.delete_signature(sid))
        m.exec(self.sig_list.viewport().mapToGlobal(pos))
