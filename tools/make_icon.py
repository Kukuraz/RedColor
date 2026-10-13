# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Рисует иконку RedColor (PNG + ICO) в папку assets."""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QTransform)

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    p.scale(s, s)
    # фон
    g = QLinearGradient(0, 0, 0, 256)
    g.setColorAt(0, QColor("#f2353c"))
    g.setColorAt(1, QColor("#b3121b"))
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8, 8, 240, 240), 54, 54)
    p.fillPath(bg, g)
    # лист
    page = QPainterPath()
    x0, y0, x1, y1, f = 58, 42, 170, 206, 34
    page.moveTo(x0 + 10, y0)
    page.lineTo(x1 - f, y0)
    page.lineTo(x1, y0 + f)
    page.lineTo(x1, y1 - 10)
    page.quadTo(x1, y1, x1 - 10, y1)
    page.lineTo(x0 + 10, y1)
    page.quadTo(x0, y1, x0, y1 - 10)
    page.lineTo(x0, y0 + 10)
    page.quadTo(x0, y0, x0 + 10, y0)
    p.fillPath(page.translated(0, 5), QColor(90, 0, 5, 70))
    p.fillPath(page, QColor("#ffffff"))
    fold = QPainterPath()
    fold.moveTo(x1 - f, y0)
    fold.lineTo(x1 - f, y0 + f - 6)
    fold.quadTo(x1 - f, y0 + f, x1 - f + 6, y0 + f)
    fold.lineTo(x1, y0 + f)
    fold.closeSubpath()
    p.fillPath(fold, QColor("#ffc9cc"))
    # строки текста
    p.setPen(QPen(QColor("#f6b3b6"), 9, Qt.SolidLine, Qt.RoundCap))
    for y, w in ((92, 70), (114, 82), (136, 58)):
        p.drawLine(QPointF(x0 + 20, y), QPointF(x0 + 20 + w, y))
    # красная пометка-галочка
    p.setPen(QPen(QColor("#d4141d"), 11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    ck = QPainterPath()
    ck.moveTo(80, 170)
    ck.lineTo(98, 186)
    ck.lineTo(132, 152)
    p.drawPath(ck)
    # ручка
    p.save()
    p.translate(178, 150)
    p.rotate(42)
    body = QPainterPath()
    body.addRoundedRect(QRectF(-15, -92, 30, 112), 9, 9)
    p.fillPath(body.translated(4, 5), QColor(80, 0, 5, 80))
    p.fillPath(body, QColor("#ffffff"))
    p.fillRect(QRectF(-15, -64, 30, 10), QColor("#d4141d"))
    tip = QPainterPath()
    tip.moveTo(-15, 20)
    tip.lineTo(15, 20)
    tip.lineTo(3, 50)
    tip.quadTo(0, 55, -3, 50)
    tip.closeSubpath()
    p.fillPath(tip, QColor("#ffe2e3"))
    nib = QPainterPath()
    nib.moveTo(-5, 40)
    nib.lineTo(5, 40)
    nib.lineTo(1.5, 50)
    nib.quadTo(0, 53, -1.5, 50)
    nib.closeSubpath()
    p.fillPath(nib, QColor("#8a0b11"))
    p.restore()
    p.end()
    return img


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    ASSETS.mkdir(exist_ok=True)
    big = draw(512)
    big.save(str(ASSETS / "redcolor_512.png"))
    draw(256).save(str(ASSETS / "redcolor_256.png"))
    from PIL import Image
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    tmp = []
    for sz in sizes:
        path = ASSETS / f"_ic{sz}.png"
        draw(sz).save(str(path))
        tmp.append(path)
    ims = [Image.open(t).convert("RGBA") for t in tmp]
    ims[-1].save(str(ASSETS / "redcolor.ico"), sizes=[(i.width, i.height) for i in ims], append_images=ims[:-1])
    for im in ims:
        im.close()
    for t in tmp:
        t.unlink()
    print("ok")


if __name__ == "__main__":
    main()
