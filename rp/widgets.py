# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Небольшие виджеты в стиле интерфейса Acrobat."""
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPolygonF
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from . import icons
from .theme import T

SWATCHES = ["#ff0000", "#d4141d", "#c00000", "#000000", "#404040", "#808080", "#1f4fd6", "#0070c0",
            "#00a050", "#118a2e", "#ff8c00", "#ffd400", "#7030a0", "#e0007a", "#00a3a3", "#ffffff"]


def section(text):
    l = QLabel(text.upper())
    l.setObjectName("section")
    return l


def separator():
    f = QFrame()
    f.setObjectName("sep")
    f.setFixedHeight(1)
    return f


class IconButton(QToolButton):
    """Кнопка-иконка (как в Acrobat); при наличии меню рисует маленький треугольник в углу."""

    def __init__(self, icon_name, tip="", size=20, parent=None, action=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setIconSize(QSize(size, size))
        if action is not None:
            self.setDefaultAction(action)
        self.setIcon(icons.icon(icon_name))
        if tip:
            self.setToolTip(tip)
        self.setAutoRaise(True)
        self.setCursor(Qt.ArrowCursor)
        self._sub_menu = None

    def set_sub_menu(self, menu):
        self._sub_menu = menu

    def mousePressEvent(self, e):
        if self._sub_menu is not None and e.button() == Qt.LeftButton:
            r = self.rect()
            if e.position().x() > r.width() - 11 and e.position().y() > r.height() - 11:
                self._sub_menu.exec(self.mapToGlobal(QPoint(r.width() + 4, 0)))
                return
        if self._sub_menu is not None and e.button() == Qt.RightButton:
            self._sub_menu.exec(self.mapToGlobal(QPoint(self.width() + 4, 0)))
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        if self._sub_menu is not None:
            return
        super().contextMenuEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._sub_menu is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff" if self.isChecked() else T["icon"]))
            w, h = self.width(), self.height()
            p.drawPolygon(QPolygonF([QPointF(w - 3, h - 8), QPointF(w - 3, h - 3), QPointF(w - 8, h - 3)]))
            p.end()


class PanelRow(QToolButton):
    """Строка левой панели: иконка + текст (как «Систематизация страниц», «Текст»)."""

    def __init__(self, icon_name, text, parent=None, action=None, submenu=False):
        super().__init__(parent)
        self.setObjectName("panelrow")
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(18, 18))
        if action is not None:
            self.setDefaultAction(action)
        self.setIcon(icons.icon(icon_name))
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(32)
        self.setAutoRaise(True)
        self._submenu = submenu
        self.setCursor(Qt.PointingHandCursor)

    def setDefaultAction(self, a):
        super().setDefaultAction(a)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._submenu or self.menu() is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            fm = self.fontMetrics()
            x = 8 + 18 + 8 + fm.horizontalAdvance(self.text()) + 3
            y = self.height() / 2 + 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T["icon"]))
            p.drawPolygon(QPolygonF([QPointF(x + 5, y - 5), QPointF(x + 5, y), QPointF(x, y)]))
            p.end()


class ColorButton(QToolButton):
    """Квадрат цвета (как в Acrobat); по клику — палитра + «Другой цвет…»."""
    color_changed = Signal(str)

    def __init__(self, color="#ff0000", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(26, 26)
        self.setToolTip("Цвет")
        self.clicked.connect(self._popup)

    def color(self):
        return self._color

    def set_color(self, c, emit=False):
        self._color = c
        self.update()
        if emit:
            self.color_changed.emit(c)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(4, 4, -4, -4)
        p.setPen(QColor(T["border2"]))
        p.setBrush(QColor(self._color))
        p.drawRect(r)
        p.end()

    def _popup(self):
        m = QMenu(self)
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(6, 6, 6, 6)
        g.setSpacing(4)
        for i, c in enumerate(SWATCHES):
            b = QToolButton()
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"QToolButton{{background:{c};border:1px solid {T['border2']};border-radius:3px;}}"
                            f"QToolButton:hover{{border:2px solid {T['accent']};}}")
            b.clicked.connect(lambda _=False, c=c: (self.set_color(c, True), m.close()))
            g.addWidget(b, i // 8, i % 8)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.addSeparator()
        other = m.addAction("Другой цвет…")
        other.triggered.connect(self._custom)
        m.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _custom(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Цвет")
        if c.isValid():
            self.set_color(c.name(), True)


class FlatCombo(QComboBox):
    """Комбобокс с подчёркиванием, как в панели форматирования Acrobat."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QComboBox{{background:transparent;border:none;border-bottom:1px solid {T['border2']};"
            f"border-radius:0;padding:3px 2px;}}"
            f"QComboBox:focus{{border-bottom:1px solid {T['accent']};}}"
            f"QComboBox QAbstractItemView{{background:{T['menu']};border:1px solid {T['border2']};}}")


class Header(QWidget):
    """Заголовок левой панели: [‹] Название ………… ×"""
    closed = Signal()
    back = Signal()

    def __init__(self, title, with_back=False, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 10, 6)
        h.setSpacing(6)
        if with_back:
            b = IconButton("chevron_left", "Назад", 16)
            b.clicked.connect(self.back.emit)
            h.addWidget(b)
        self.label = QLabel(title)
        self.label.setObjectName("title")
        h.addWidget(self.label)
        h.addStretch(1)
        c = IconButton("close", "Закрыть", 14)
        c.clicked.connect(self.closed.emit)
        h.addWidget(c)
