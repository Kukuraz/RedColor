# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Реестр команд: у каждой команды есть горячая клавиша (по умолчанию как в Acrobat), все переназначаются."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence

from . import icons
from .config import S


class Actions(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.acts = {}
        self.meta = {}
        self.order = []

    def add(self, aid, text, default="", slot=None, icon=None, group="Общие", checkable=False):
        a = self.acts.get(aid)
        if a is None:
            a = QAction(text, self.window)
            a.setObjectName(aid)
            a.setShortcutContext(Qt.WindowShortcut)
            self.window.addAction(a)
            self.acts[aid] = a
            self.order.append(aid)
        else:
            a.setText(text)
            try:
                a.triggered.disconnect()
            except (RuntimeError, TypeError):
                pass
        if icon:
            a.setIcon(icons.icon(icon))
            a.setProperty("icon_name", icon)
        a.setCheckable(checkable)
        if slot is not None:
            a.triggered.connect(lambda checked=False, s=slot: s())
        self.meta[aid] = (group, text, default)
        self._apply(aid)
        return a

    def remove(self, aid):
        a = self.acts.pop(aid, None)
        if a is not None:
            self.window.removeAction(a)
            a.deleteLater()
        self.meta.pop(aid, None)
        if aid in self.order:
            self.order.remove(aid)

    def __getitem__(self, aid):
        return self.acts[aid]

    def get(self, aid):
        return self.acts.get(aid)

    def ordered(self):
        return list(self.order)

    def sequences(self, aid):
        val = S.get("shortcuts", {}).get(aid)
        if val is None:
            val = self.meta[aid][2]
        if isinstance(val, str):
            val = [x.strip() for x in val.split(";") if x.strip()]
        return list(val)

    def set_sequences(self, aid, seqs):
        sc = dict(S.get("shortcuts", {}))
        sc[aid] = list(seqs)
        S["shortcuts"] = sc
        S.save()
        self._apply(aid)

    def reset(self, aid):
        sc = dict(S.get("shortcuts", {}))
        sc.pop(aid, None)
        S["shortcuts"] = sc
        S.save()
        self._apply(aid)

    def who_uses(self, seq):
        ks = QKeySequence(seq)
        out = []
        for aid in self.acts:
            for s in self.sequences(aid):
                if QKeySequence(s) == ks:
                    out.append(aid)
        return out

    def _apply(self, aid):
        a = self.acts[aid]
        seqs = [QKeySequence(s) for s in self.sequences(aid)]
        a.setShortcuts(seqs)
        text = self.meta[aid][1]
        if seqs:
            a.setToolTip(f"{text} ({seqs[0].toString(QKeySequence.NativeText)})")
        else:
            a.setToolTip(text)

    def label(self, aid):
        seqs = self.sequences(aid)
        return QKeySequence(seqs[0]).toString(QKeySequence.NativeText) if seqs else ""
