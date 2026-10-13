# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Диалоги: горячие клавиши, цитаты, формула, настройки."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import fonts
from .config import S
from .theme import T
from .widgets import ColorButton


# =========================================================================== горячие клавиши
class HotkeysDialog(QDialog):
    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Горячие клавиши")
        self.resize(760, 620)
        self.A = actions
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск команды или сочетания…")
        self.search.textChanged.connect(self.fill)
        top.addWidget(self.search, 1)
        v.addLayout(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Команда", "Раздел", "Сочетание", "Дополнительное"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._sel)
        v.addWidget(self.table, 1)
        ed = QFrame()
        g = QGridLayout(ed)
        g.setContentsMargins(0, 6, 0, 0)
        self.cmd_label = QLabel("Выберите команду")
        self.cmd_label.setStyleSheet("font-weight:600")
        g.addWidget(self.cmd_label, 0, 0, 1, 4)
        g.addWidget(QLabel("Сочетание:"), 1, 0)
        self.k1 = QKeySequenceEdit()
        self.k1.setMaximumSequenceLength(1)
        g.addWidget(self.k1, 1, 1)
        g.addWidget(QLabel("Дополнительное:"), 1, 2)
        self.k2 = QKeySequenceEdit()
        self.k2.setMaximumSequenceLength(1)
        g.addWidget(self.k2, 1, 3)
        for k in (self.k1, self.k2):
            le = k.findChild(QLineEdit)
            if le is not None:
                le.setPlaceholderText("Нажмите сочетание")
        self.k1.editingFinished.connect(self._apply)
        self.k2.editingFinished.connect(self._apply)
        row = QHBoxLayout()
        b_clear = QPushButton("Очистить")
        b_clear.clicked.connect(self._clear)
        b_def = QPushButton("По умолчанию")
        b_def.clicked.connect(self._default)
        row.addWidget(b_clear)
        row.addWidget(b_def)
        row.addStretch(1)
        self.conflict = QLabel("")
        self.conflict.setStyleSheet("color:#ff6b6b")
        row.addWidget(self.conflict)
        g.addLayout(row, 2, 0, 1, 4)
        v.addWidget(ed)
        bottom = QHBoxLayout()
        reset_all = QPushButton("Сбросить все")
        reset_all.clicked.connect(self._reset_all)
        bottom.addWidget(reset_all)
        bottom.addStretch(1)
        close = QPushButton("Готово")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        v.addLayout(bottom)
        self.current = None
        self.fill()

    def fill(self):
        q = self.search.text().strip().lower()
        self.table.setRowCount(0)
        for aid in self.A.ordered():
            group, text, default = self.A.meta[aid]
            seqs = self.A.sequences(aid)
            s1 = seqs[0] if seqs else ""
            s2 = seqs[1] if len(seqs) > 1 else ""
            if q and q not in text.lower() and q not in group.lower() and q not in s1.lower() and q not in s2.lower():
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(text)
            it.setData(Qt.UserRole, aid)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(group))
            self.table.setItem(r, 2, QTableWidgetItem(QKeySequence(s1).toString(QKeySequence.NativeText) if s1 else ""))
            self.table.setItem(r, 3, QTableWidgetItem(QKeySequence(s2).toString(QKeySequence.NativeText) if s2 else ""))
            if self.current == aid:
                self.table.selectRow(r)

    def _sel(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        aid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        self.current = aid
        self.cmd_label.setText(self.A.meta[aid][1])
        seqs = self.A.sequences(aid)
        self.k1.blockSignals(True)
        self.k2.blockSignals(True)
        self.k1.setKeySequence(QKeySequence(seqs[0]) if seqs else QKeySequence())
        self.k2.setKeySequence(QKeySequence(seqs[1]) if len(seqs) > 1 else QKeySequence())
        self.k1.blockSignals(False)
        self.k2.blockSignals(False)
        self._check()

    def _apply(self):
        if not self.current:
            return
        s = [k.keySequence().toString(QKeySequence.PortableText) for k in (self.k1, self.k2)]
        s = [x for x in s if x]
        self.A.set_sequences(self.current, s)
        self._check()
        self.fill()

    def _check(self):
        if not self.current:
            return
        msgs = []
        for s in self.A.sequences(self.current):
            for other in self.A.who_uses(s):
                if other != self.current:
                    msgs.append(f"«{s}» уже у «{self.A.meta[other][1]}»")
        self.conflict.setText("; ".join(msgs))

    def _clear(self):
        if self.current:
            self.A.set_sequences(self.current, [])
            self._sel()
            self.fill()

    def _default(self):
        if self.current:
            self.A.reset(self.current)
            self._sel()
            self.fill()

    def _reset_all(self):
        if QMessageBox.question(self, "Горячие клавиши", "Вернуть все сочетания по умолчанию?") == QMessageBox.Yes:
            for aid in list(self.A.acts):
                self.A.reset(aid)
            self.fill()


# =========================================================================== цитаты
class QuotesDialog(QDialog):
    def __init__(self, bank, parent=None):
        super().__init__(parent)
        self.bank = bank
        self.setWindowTitle("Цитаты")
        self.resize(700, 560)
        v = QVBoxLayout(self)
        info = QLabel(f"Случайная цитата ставится при вставке бланка (на место «1» или под «Комментарий эксперта:») "
                      f"и инструментом «Цитата». Файл: {bank.path}")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{T['text2']}")
        v.addWidget(info)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        self.count = QLabel("")
        top.addWidget(self.count)
        v.addLayout(top)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._edit)
        self.list.model().rowsMoved.connect(lambda *a: self._dirty())
        v.addWidget(self.list, 1)
        add_row = QHBoxLayout()
        self.new = QLineEdit()
        self.new.setPlaceholderText("Новая цитата — Enter, чтобы добавить")
        self.new.returnPressed.connect(self._add)
        add_row.addWidget(self.new, 1)
        b = QPushButton("Добавить")
        b.clicked.connect(self._add)
        add_row.addWidget(b)
        v.addLayout(add_row)
        row = QHBoxLayout()
        for text, fn in (("Изменить", lambda: self._edit(self.list.currentItem())), ("Удалить", self._delete),
                         ("Импорт из файла…", self._import), ("Экспорт…", self._export),
                         ("Открыть в Блокноте", self._notepad)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        row.addStretch(1)
        v.addLayout(row)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        bottom.addWidget(cancel)
        bottom.addWidget(ok)
        v.addLayout(bottom)
        for q in bank.quotes:
            self._item(q)
        self._count()

    def _item(self, text):
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
        self.list.addItem(it)
        return it

    def _count(self):
        self.count.setText(f"{self.list.count()} шт.")

    def _dirty(self):
        self._count()

    def _filter(self, q):
        q = q.lower().strip()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(q) and q not in it.text().lower())

    def _add(self):
        t = self.new.text().strip()
        if not t:
            return
        it = self._item(t)
        self.list.scrollToItem(it)
        self.new.clear()
        self._count()

    def _edit(self, it):
        if it is not None:
            self.list.editItem(it)

    def _delete(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._count()

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "Импорт цитат", S.get("last_dir", ""), "Текст (*.txt);;Все файлы (*.*)")
        if not p:
            return
        raw = Path(p).read_bytes()
        for enc in ("utf-8-sig", "cp1251", "utf-16"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            txt = raw.decode("utf-8", "replace")
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        mb = QMessageBox(self)
        mb.setWindowTitle("Импорт")
        mb.setText(f"Найдено цитат: {len(lines)}")
        add = mb.addButton("Добавить к списку", QMessageBox.AcceptRole)
        rep = mb.addButton("Заменить список", QMessageBox.DestructiveRole)
        mb.addButton("Отмена", QMessageBox.RejectRole)
        mb.exec()
        if mb.clickedButton() == rep:
            self.list.clear()
        elif mb.clickedButton() != add:
            return
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for l in lines:
            if l not in existing:
                self._item(l)
                existing.add(l)
        self._count()

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "Экспорт цитат", "цитаты.txt", "Текст (*.txt)")
        if p:
            Path(p).write_text(self._text(), encoding="utf-8")

    def _notepad(self):
        import os
        self._save(close=False)
        os.startfile(str(self.bank.path))

    def _text(self):
        return "\n".join(self.list.item(i).text().strip() for i in range(self.list.count())
                         if self.list.item(i).text().strip())

    def _save(self, close=True):
        self.bank.save(self._text())
        if close:
            self.accept()


# =========================================================================== формула
class FormulaDialog(QDialog):
    SNIPPETS = [("a/b", r"\frac{}{}"), ("√", r"\sqrt{}"), ("x²", "^{}"), ("x₁", "_{}"), ("→", r"\vec{}"),
                ("·", r"\cdot "), ("≈", r"\approx "), ("±", r"\pm "), ("Δ", r"\Delta "), ("α", r"\alpha "),
                ("μ", r"\mu "), ("π", r"\pi "), ("ω", r"\omega "), ("ν", r"\nu "), ("ρ", r"\rho "),
                ("{ система", "\\begin{cases}  \\\\  \\end{cases}"), ("текст", r"\text{}"), ("°", r"^\circ ")]

    def __init__(self, latex="", hint="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Формула")
        self.resize(760, 480)
        v = QVBoxLayout(self)
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet(f"color:{T['text2']}")
            v.addWidget(h)
        grid = QGridLayout()
        for i, (lab, snip) in enumerate(self.SNIPPETS):
            b = QToolButton()
            b.setText(lab)
            b.setToolTip(snip)
            b.setMinimumWidth(34)
            b.clicked.connect(lambda _=False, s=snip: self._insert(s))
            grid.addWidget(b, 0 if i < 9 else 1, i % 9)
        v.addLayout(grid)
        self.edit = QPlainTextEdit(latex)
        self.edit.setPlaceholderText(r"Например: \nu = \frac{1}{2\pi}\sqrt{\frac{T(m_1+m_2)}{m_1 m_2 l}}")
        f = self.edit.font()
        f.setFamily("Consolas")
        f.setPointSize(11)
        self.edit.setFont(f)
        self.edit.setMaximumHeight(140)
        v.addWidget(self.edit)
        self.preview_box = QFrame()
        self.preview_box.setStyleSheet("background:#ffffff;border-radius:6px;")
        pv = QVBoxLayout(self.preview_box)
        self.preview = QSvgWidget()
        pv.addWidget(self.preview, 0, Qt.AlignCenter)
        v.addWidget(self.preview_box, 1)
        self.err = QLabel("")
        self.err.setStyleSheet("color:#ff6b6b")
        v.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Вставить")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.result = None
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(250)
        self._t.timeout.connect(self._render)
        self.edit.textChanged.connect(self._t.start)
        self._render()

    def _insert(self, s):
        c = self.edit.textCursor()
        c.insertText(s)
        pos = s.find("{}")
        if pos >= 0:
            c.setPosition(c.position() - len(s) + pos + 1)
            self.edit.setTextCursor(c)
        self.edit.setFocus()

    def _render(self):
        from .formula import render_latex
        tex = self.edit.toPlainText().strip()
        if not tex:
            self.preview.load(QByteArray(b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>"))
            return
        try:
            svg, w, h = render_latex(tex, 20)
            svg = svg.replace("<svg", "<svg fill='#d00000'", 1)
            self.preview.load(QByteArray(svg.encode("utf-8")))
            sc = min(1.6, 700 / max(w, 1), 260 / max(h, 1))
            self.preview.setFixedSize(QSize(int(w * sc * 1.33), int(h * sc * 1.33)))
            self.err.setText("")
        except Exception as e:
            self.err.setText("Ошибка: " + str(e).splitlines()[0][:200])

    def _ok(self):
        from .formula import from_latex
        tex = self.edit.toPlainText().strip()
        if not tex:
            self.reject()
            return
        try:
            self.result = from_latex(tex, 12.0)
        except Exception as e:
            self.err.setText("Ошибка: " + str(e).splitlines()[0][:200])
            return
        self.accept()


# =========================================================================== настройки
class SettingsDialog(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.setWindowTitle("Настройки RedColor")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        # --- Текст
        w = QWidget()
        f = QFormLayout(w)
        self.font = QComboBox()
        fav, rest = fonts.families()
        self.font.addItems(fav + rest)
        self.font.setCurrentText(fonts.resolve(S["text_font"]))
        f.addRow("Шрифт по умолчанию:", self.font)
        self.color = ColorButton(S["text_color"])
        cr = QHBoxLayout()
        cr.addWidget(self.color)
        red = QPushButton("Красный")
        red.clicked.connect(lambda: self.color.set_color("#ff0000"))
        cr.addWidget(red)
        cr.addStretch(1)
        f.addRow("Цвет текста по умолчанию:", cr)
        self.auto = QCheckBox("Подстраивать размер под ширину страницы")
        self.auto.setChecked(S["text_size_auto"])
        f.addRow("", self.auto)
        self.pct = QDoubleSpinBox()
        self.pct.setRange(0.5, 10)
        self.pct.setSingleStep(0.1)
        self.pct.setSuffix(" % ширины")
        self.pct.setValue(S["auto_size_pct"])
        f.addRow("Авторазмер:", self.pct)
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 200)
        self.size.setValue(S["text_size"])
        f.addRow("Размер (если не авто):", self.size)
        tabs.addTab(w, "Текст")
        # --- Бланки и цитаты
        w2 = QWidget()
        f2 = QFormLayout(w2)
        bd = QHBoxLayout()
        self.blanks = QLineEdit(S["blanks_dir"])
        bb = QPushButton("…")
        bb.clicked.connect(lambda: self._pick_dir(self.blanks))
        bd.addWidget(self.blanks, 1)
        bd.addWidget(bb)
        f2.addRow("Папка бланков:", bd)
        qd = QHBoxLayout()
        self.qfile = QLineEdit(S["quotes_file"])
        qb = QPushButton("…")
        qb.clicked.connect(self._pick_quotes)
        qd.addWidget(self.qfile, 1)
        qd.addWidget(qb)
        f2.addRow("Файл цитат:", qd)
        self.autoq = QCheckBox("Ставить случайную цитату при вставке бланка")
        self.autoq.setChecked(S["auto_quote_on_blank"])
        f2.addRow("", self.autoq)
        self.rm1 = QCheckBox("Удалять красную «1» с бланка (цитата встаёт на её место)")
        self.rm1.setChecked(S["remove_stray_one"])
        f2.addRow("", self.rm1)
        self.rm1_open = QCheckBox("Убирать «1» в комментариях бланков при открытии документа")
        self.rm1_open.setChecked(S.get("auto_remove_ones", True))
        f2.addRow("", self.rm1_open)
        self.qfont = QComboBox()
        self.qfont.addItems(fav + rest)
        self.qfont.setCurrentText(fonts.resolve(S["quote_font"]))
        f2.addRow("Шрифт цитаты:", self.qfont)
        self.qsize = QDoubleSpinBox()
        self.qsize.setRange(5, 60)
        self.qsize.setValue(S["quote_default_size"])
        f2.addRow("Размер цитаты (если нет «1»):", self.qsize)
        tabs.addTab(w2, "Бланки и цитаты")
        # --- Внешний вид
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.theme = QComboBox()
        self.theme.addItems(["Тёмная", "Светлая"])
        self.theme.setCurrentIndex(1 if S["theme"] == "light" else 0)
        f3.addRow("Тема:", self.theme)
        self.accent = ColorButton(S["accent"])
        f3.addRow("Акцентный цвет:", self.accent)
        self.ink = ColorButton(S["ink_color"])
        f3.addRow("Цвет карандаша и фигур:", self.ink)
        self.inkw = QDoubleSpinBox()
        self.inkw.setRange(0.3, 20)
        self.inkw.setSingleStep(0.25)
        self.inkw.setValue(S["ink_width"])
        f3.addRow("Толщина линий:", self.inkw)
        self.hl = ColorButton(S["hl_color"])
        f3.addRow("Цвет маркера:", self.hl)
        tabs.addTab(w3, "Вид и рисование")
        bbx = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbx.button(QDialogButtonBox.Ok).setText("Сохранить")
        bbx.button(QDialogButtonBox.Ok).setObjectName("primary")
        bbx.button(QDialogButtonBox.Cancel).setText("Отмена")
        bbx.accepted.connect(self._save)
        bbx.rejected.connect(self.reject)
        v.addWidget(bbx)

    def _pick_dir(self, le):
        d = QFileDialog.getExistingDirectory(self, "Папка", le.text())
        if d:
            le.setText(d)

    def _pick_quotes(self):
        p, _ = QFileDialog.getOpenFileName(self, "Файл цитат", self.qfile.text(), "Текст (*.txt)")
        if p:
            self.qfile.setText(p)

    def _save(self):
        theme_changed = (S["theme"] == "light") != (self.theme.currentIndex() == 1) or S["accent"] != self.accent.color()
        S.update({
            "text_font": self.font.currentText(), "text_color": self.color.color(),
            "text_size_auto": self.auto.isChecked(), "auto_size_pct": self.pct.value(), "text_size": self.size.value(),
            "blanks_dir": self.blanks.text(), "quotes_file": self.qfile.text(),
            "auto_quote_on_blank": self.autoq.isChecked(), "remove_stray_one": self.rm1.isChecked(),
            "auto_remove_ones": self.rm1_open.isChecked(),
            "quote_font": self.qfont.currentText(), "quote_default_size": self.qsize.value(),
            "theme": "light" if self.theme.currentIndex() == 1 else "dark", "accent": self.accent.color(),
            "ink_color": self.ink.color(), "shape_color": self.ink.color(), "ink_width": self.inkw.value(),
            "shape_width": self.inkw.value(), "hl_color": self.hl.color(),
        })
        S.save()
        self.main.settings_applied(theme_changed)
        self.accept()


# =========================================================================== инструкция
class InfoDialog(QDialog):
    def __init__(self, parent=None):
        from PySide6.QtWidgets import QTextBrowser
        from .config import ASSETS
        super().__init__(parent)
        self.setWindowTitle("RedColor — информация")
        self.resize(820, 760)
        v = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setStyleSheet(f"QTextBrowser{{background:{T['panel']};border:none;padding:8px 14px;}}")
        try:
            html = (ASSETS / "info.html").read_text(encoding="utf-8")
        except OSError:
            html = "<p>Файл инструкции не найден.</p>"
        html = html.replace("#8f8f8f", T["text3"])
        tb.setHtml(html)
        v.addWidget(tb, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Закрыть")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)
