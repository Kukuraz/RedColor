# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Плавающая панель инструментов: свой набор и порядок кнопок, поворот, закрепление, прикрепление к краю."""
import copy

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QBoxLayout, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from . import icons
from .config import S
from .theme import T
from .widgets import IconButton

GROUPS = {
    "group:draw": ("Группа: карандаш / маркер / ластик", ["tool.pencil", "tool.highlighter", "tool.eraser"]),
    "group:shapes": ("Группа: фигуры", ["tool.ellipse", "tool.ellipse_num", "tool.rect", "tool.line", "tool.arrow"]),
    "group:marks": ("Группа: отметки ✓ ✗ + – •", ["tool.check", "tool.cross", "tool.plus", "tool.minus", "tool.dot"]),
    "group:sign": ("Группа: подписи", ["tool.signature"]),
}
SPECIAL = {"sep": "— Разделитель —", "more": "Ещё (⋯): цитата, формула, картинка, бланки, настройка"}
DEFAULT = {"items": ["tool.select", "group:draw", "group:shapes", "tool.text", "group:marks", "group:sign", "more"],
           "orient": "v", "pinned": False, "dock": "free", "pos": [0.0, 0.0], "size": 20, "visible": True}
DOCKS = [("free", "Свободно"), ("left", "Слева"), ("right", "Справа"), ("top", "Сверху"), ("bottom", "Снизу")]


def config():
    c = copy.deepcopy(DEFAULT)
    c.update(S.get("floatbar") or {})
    return c


def save_config(c):
    S["floatbar"] = c
    S.save()


def item_title(A, key):
    if key in GROUPS:
        return GROUPS[key][0]
    if key in SPECIAL:
        return SPECIAL[key]
    a = A.get(key)
    return A.meta[key][1] if a is not None else key


def item_icon(A, key):
    if key in GROUPS:
        a = A.get(GROUPS[key][1][0])
        return a.icon() if a is not None else icons.icon("more")
    if key == "more":
        return icons.icon("more")
    if key == "sep":
        return icons.icon("minus")
    a = A.get(key)
    if a is not None and not a.icon().isNull():
        return a.icon()
    return icons.icon("more")


class GroupButton(IconButton):
    """Кнопка группы инструментов: щелчок — последний выбранный, треугольник/правая кнопка — список."""

    def __init__(self, A, ids, size, extra_menu=None, parent=None):
        a0 = A[ids[0]]
        super().__init__(a0.property("icon_name") or "more", a0.toolTip(), size, parent)
        self.A = A
        self.ids = [i for i in ids if A.get(i) is not None]
        self.cur = self.ids[0]
        self.setCheckable(True)
        m = QMenu(self)
        self._conns = []
        for aid in self.ids:
            m.addAction(A[aid])
            self._conns.append(A[aid].triggered.connect(lambda _=False, aid=aid: self._set(aid)))
            self._conns.append(A[aid].toggled.connect(lambda _=False: self._sync()))
        if extra_menu is not None:
            m.addSeparator()
            m.addMenu(extra_menu)
        self.set_sub_menu(m)
        self.clicked.connect(lambda: self.A[self.cur].trigger())
        self._sync()

    def dispose(self):
        from PySide6.QtCore import QObject
        for c in self._conns:
            try:
                QObject.disconnect(c)
            except (RuntimeError, TypeError):
                pass
        self._conns = []

    def _set(self, aid):
        self.cur = aid
        self._sync()

    def _sync(self):
        try:
            a = self.A[self.cur]
            self.setIcon(a.icon())
            self.setToolTip(a.toolTip())
            self.setChecked(any(self.A[i].isChecked() for i in self.ids))
        except RuntimeError:
            pass


class Grip(QFrame):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.setObjectName("grip")
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Перетащите, чтобы переместить. Правый щелчок — настройка панели")


class FloatBar(QFrame):
    def __init__(self, main, parent):
        super().__init__(parent)
        self.main = main
        self.setObjectName("floatbar")
        self._drag = None
        self._buttons = []
        self.lay = QBoxLayout(QBoxLayout.TopToBottom, self)
        self.rebuild()

    # ---------------------------------------------------------------- построение
    def rebuild(self):
        c = config()
        for b in self._buttons:
            if isinstance(b, GroupButton):
                b.dispose()
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._buttons = []
        vert = c["orient"] == "v"
        self.lay.setDirection(QBoxLayout.TopToBottom if vert else QBoxLayout.LeftToRight)
        if vert:
            self.lay.setContentsMargins(4, 6, 4, 6)
        else:
            self.lay.setContentsMargins(6, 4, 6, 4)
        self.lay.setSpacing(4)
        size = int(c.get("size", 20))
        btn = size + 12
        grip = Grip(self)
        grip.setFixedSize(*((22, 3) if vert else (3, 22)))
        grip.setVisible(not c["pinned"])
        self.lay.addWidget(grip, 0, Qt.AlignHCenter if vert else Qt.AlignVCenter)
        if not c["pinned"]:
            self.lay.addSpacing(2)
        for key in c["items"]:
            w = self._make(key, size, vert)
            if w is None:
                continue
            if not isinstance(w, QFrame) or w.objectName() != "barsep":
                w.setFixedSize(btn, btn)
            self.lay.addWidget(w, 0, Qt.AlignHCenter if vert else Qt.AlignVCenter)
            self._buttons.append(w)
        self.adjustSize()
        self.setVisible(c.get("visible", True))
        QTimer.singleShot(0, self.place)

    def _make(self, key, size, vert):
        A = self.main.A
        if key == "sep":
            f = QFrame()
            f.setObjectName("barsep")
            f.setStyleSheet(f"#barsep{{background:{T['border2']};}}")
            f.setFixedSize(*((size + 4, 1) if vert else (1, size + 4)))
            return f
        if key == "more":
            more = IconButton("more", "Ещё", size)
            mm = QMenu(self)
            for aid in ("tool.quote", "tool.formula", "tool.image", "tool.hand"):
                if A.get(aid) is not None:
                    mm.addAction(A[aid])
            mm.addMenu(self.main.blank_menu)
            mm.addSeparator()
            self._fill_settings_menu(mm)
            more.setMenu(mm)
            more.setPopupMode(QToolButton.InstantPopup)
            return more
        if key in GROUPS:
            ids = [i for i in GROUPS[key][1] if A.get(i) is not None]
            if not ids:
                return None
            return GroupButton(A, ids, size, self.main.sign_menu if key == "group:sign" else None)
        a = A.get(key)
        if a is None:
            return None
        b = IconButton(a.property("icon_name") or "more", a.toolTip(), size, action=a)
        if a.icon().isNull():
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setText(_short(A.meta[key][1]))
            b.setStyleSheet("font-size:10px;padding:0;")
        else:
            b.setIcon(a.icon())
        return b

    # ---------------------------------------------------------------- положение
    def place(self):
        par = self.parentWidget()
        if par is None:
            return
        c = config()
        self.adjustSize()
        W, H = par.width(), par.height()
        w, h = self.width(), self.height()
        m = 12
        dock = c.get("dock", "free")
        if dock == "left":
            x, y = m, m
        elif dock == "right":
            x, y = W - w - m, m
        elif dock == "top":
            x, y = (W - w) // 2, m
        elif dock == "bottom":
            x, y = (W - w) // 2, H - h - m
        else:
            fx, fy = c.get("pos", [0.0, 0.0])
            x = int(m + fx * max(W - w - 2 * m, 1))
            y = int(m + fy * max(H - h - 2 * m, 1))
        self.move(max(0, min(x, W - w)), max(0, min(y, H - h)))
        self.raise_()

    def _save_pos(self):
        par = self.parentWidget()
        c = config()
        m = 12
        W, H = par.width(), par.height()
        c["pos"] = [round(max(0.0, min(1.0, (self.x() - m) / max(W - self.width() - 2 * m, 1))), 4),
                    round(max(0.0, min(1.0, (self.y() - m) / max(H - self.height() - 2 * m, 1))), 4)]
        c["dock"] = "free"
        save_config(c)
        self.main.floatbar_changed(rebuild=False, source=self)

    # ---------------------------------------------------------------- мышь
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not config()["pinned"]:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            p = e.globalPosition().toPoint() - self._drag
            par = self.parentWidget().rect()
            p.setX(max(0, min(p.x(), par.width() - self.width())))
            p.setY(max(0, min(p.y(), par.height() - self.height())))
            self.move(p)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self._save_pos()

    def mouseDoubleClickEvent(self, e):
        self.main.floatbar_set(orient="h" if config()["orient"] == "v" else "v")

    def contextMenuEvent(self, e):
        m = QMenu(self)
        self._fill_settings_menu(m)
        m.exec(e.globalPos())

    def _fill_settings_menu(self, m):
        c = config()
        main = self.main
        m.addAction(icons.icon("sliders"), "Настроить панель…", main.customize_floatbar)
        rot = m.addAction(icons.icon("rotate_cw"),
                          "Повернуть: горизонтально" if c["orient"] == "v" else "Повернуть: вертикально")
        rot.triggered.connect(lambda: main.floatbar_set(orient="h" if config()["orient"] == "v" else "v"))
        pin = m.addAction("Закрепить (не перемещать)")
        pin.setCheckable(True)
        pin.setChecked(c["pinned"])
        pin.toggled.connect(lambda b: main.floatbar_set(pinned=b))
        dm = m.addMenu("Положение")
        for key, title in DOCKS:
            a = dm.addAction(title)
            a.setCheckable(True)
            a.setChecked(c.get("dock", "free") == key)
            a.triggered.connect(lambda _=False, key=key: main.floatbar_set(dock=key))
        sm = m.addMenu("Размер значков")
        for s, title in ((16, "Мелкие"), (20, "Средние"), (26, "Крупные")):
            a = sm.addAction(title)
            a.setCheckable(True)
            a.setChecked(int(c.get("size", 20)) == s)
            a.triggered.connect(lambda _=False, s=s: main.floatbar_set(size=s))
        m.addSeparator()
        m.addAction("Скрыть панель", lambda: main.floatbar_set(visible=False))
        m.addAction("Сбросить панель", main.reset_floatbar)


def _short(text):
    words = [w for w in text.replace("…", "").replace("«", "").replace("»", "").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3]
    return (words[0][0] + words[1][0]).upper()


# =========================================================================== редактор панели
class ToolbarEditor(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.A = main.A
        self.setWindowTitle("Настройка панели инструментов")
        self.resize(820, 600)
        v = QVBoxLayout(self)
        tip = QLabel("Добавляйте, убирайте и перетаскивайте кнопки. Изменения сразу видны на панели. "
                     "На панель можно вынести любую команду — в том числе отдельный бланк или подпись.")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{T['text2']}")
        v.addWidget(tip)
        g = QGridLayout()
        g.addWidget(QLabel("Доступные команды"), 0, 0)
        g.addWidget(QLabel("На панели (перетаскивайте для порядка)"), 0, 2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self.fill_available)
        g.addWidget(self.search, 1, 0)
        self.avail = QListWidget()
        self.avail.setIconSize(QSize(18, 18))
        self.avail.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.avail.itemDoubleClicked.connect(lambda *_: self.add())
        g.addWidget(self.avail, 2, 0)
        mid = QVBoxLayout()
        mid.addStretch(1)
        for text, fn in (("Добавить →", self.add), ("← Убрать", self.remove), ("Выше ↑", lambda: self.move(-1)),
                         ("Ниже ↓", lambda: self.move(1)), ("Разделитель", self.add_sep)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            mid.addWidget(b)
        mid.addStretch(1)
        g.addLayout(mid, 2, 1)
        self.cur = QListWidget()
        self.cur.setIconSize(QSize(18, 18))
        self.cur.setDragDropMode(QAbstractItemView.InternalMove)
        self.cur.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cur.itemDoubleClicked.connect(lambda *_: self.remove())
        self.cur.model().rowsMoved.connect(lambda *a: QTimer.singleShot(0, self.apply))
        g.addWidget(self.cur, 1, 2, 2, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)
        v.addLayout(g, 1)
        opts = QHBoxLayout()
        c = config()
        opts.addWidget(QLabel("Направление:"))
        self.orient = QComboBox()
        self.orient.addItems(["Вертикально", "Горизонтально"])
        self.orient.setCurrentIndex(0 if c["orient"] == "v" else 1)
        self.orient.currentIndexChanged.connect(self.apply)
        opts.addWidget(self.orient)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Положение:"))
        self.dock = QComboBox()
        for key, title in DOCKS:
            self.dock.addItem(title, key)
        self.dock.setCurrentIndex([k for k, _ in DOCKS].index(c.get("dock", "free")))
        self.dock.currentIndexChanged.connect(self.apply)
        opts.addWidget(self.dock)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Значки:"))
        self.size = QComboBox()
        for s, title in ((16, "Мелкие"), (20, "Средние"), (26, "Крупные")):
            self.size.addItem(title, s)
        self.size.setCurrentIndex({16: 0, 20: 1, 26: 2}.get(int(c.get("size", 20)), 1))
        self.size.currentIndexChanged.connect(self.apply)
        opts.addWidget(self.size)
        opts.addSpacing(12)
        self.pinned = QCheckBox("Закрепить")
        self.pinned.setChecked(c["pinned"])
        self.pinned.toggled.connect(self.apply)
        opts.addWidget(self.pinned)
        self.visible = QCheckBox("Показывать панель")
        self.visible.setChecked(c.get("visible", True))
        self.visible.toggled.connect(self.apply)
        opts.addWidget(self.visible)
        opts.addStretch(1)
        v.addLayout(opts)
        bottom = QHBoxLayout()
        reset = QPushButton("Сбросить по умолчанию")
        reset.clicked.connect(self.reset)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        ok = QPushButton("Готово")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        v.addLayout(bottom)
        self.fill_current(c["items"])
        self.fill_available()

    def _item(self, key):
        it = QListWidgetItem(item_icon(self.A, key), item_title(self.A, key))
        it.setData(Qt.UserRole, key)
        return it

    def keys(self):
        return [self.cur.item(i).data(Qt.UserRole) for i in range(self.cur.count())]

    def fill_current(self, items):
        self.cur.clear()
        for k in items:
            if k in GROUPS or k in SPECIAL or self.A.get(k) is not None:
                self.cur.addItem(self._item(k))

    def fill_available(self):
        q = self.search.text().strip().lower()
        used = set(self.keys())
        self.avail.clear()
        keys = list(GROUPS) + ["more"] + self.A.ordered()
        for k in keys:
            if k in used and k != "sep":
                continue
            title = item_title(self.A, k)
            group = self.A.meta[k][0] if k in self.A.meta else "Группы"
            if q and q not in title.lower() and q not in group.lower():
                continue
            it = self._item(k)
            it.setText(f"{title}   ·  {group}")
            self.avail.addItem(it)

    def add(self):
        sel = self.avail.selectedItems()
        if not sel:
            return
        row = self.cur.currentRow() + 1 if self.cur.currentRow() >= 0 else self.cur.count()
        for it in sel:
            self.cur.insertItem(row, self._item(it.data(Qt.UserRole)))
            row += 1
        self.apply()
        self.fill_available()

    def add_sep(self):
        row = self.cur.currentRow() + 1 if self.cur.currentRow() >= 0 else self.cur.count()
        self.cur.insertItem(row, self._item("sep"))
        self.apply()

    def remove(self):
        for it in self.cur.selectedItems():
            self.cur.takeItem(self.cur.row(it))
        self.apply()
        self.fill_available()

    def move(self, d):
        row = self.cur.currentRow()
        if row < 0:
            return
        nr = row + d
        if 0 <= nr < self.cur.count():
            it = self.cur.takeItem(row)
            self.cur.insertItem(nr, it)
            self.cur.setCurrentRow(nr)
            self.apply()

    def reset(self):
        save_config(copy.deepcopy(DEFAULT))
        c = config()
        for w in (self.orient, self.dock, self.size, self.pinned, self.visible):
            w.blockSignals(True)
        self.orient.setCurrentIndex(0)
        self.dock.setCurrentIndex(0)
        self.size.setCurrentIndex(1)
        self.pinned.setChecked(False)
        self.visible.setChecked(True)
        for w in (self.orient, self.dock, self.size, self.pinned, self.visible):
            w.blockSignals(False)
        self.fill_current(c["items"])
        self.fill_available()
        self.main.floatbar_changed()

    def apply(self, *a):
        c = config()
        c["items"] = self.keys()
        c["orient"] = "v" if self.orient.currentIndex() == 0 else "h"
        c["dock"] = self.dock.currentData()
        c["size"] = self.size.currentData()
        c["pinned"] = self.pinned.isChecked()
        c["visible"] = self.visible.isChecked()
        save_config(c)
        self.main.floatbar_changed()
