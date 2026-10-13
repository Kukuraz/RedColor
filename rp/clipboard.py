# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Разбор вставки: HTML с формулами-картинками (SVG), KaTeX, обычный текст → блоки для TextItem."""
import re
from urllib.parse import urljoin

from . import formula as F

BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote",
              "section", "article", "pre", "center", "dd", "dt", "figure"}
SKIP_TAGS = {"script", "style", "head", "title", "meta", "link", "noscript", "button", "svg"}


def _fragment(html):
    a = html.find("<!--StartFragment-->")
    b = html.find("<!--EndFragment-->")
    if a >= 0 and b > a:
        return html[a + len("<!--StartFragment-->"):b]
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    return m.group(1) if m else html


def _source_url(html):
    m = re.search(r"^SourceURL:(\S+)", html, re.M)
    return m.group(1) if m else ""


class _Builder:
    def __init__(self):
        self.blocks = [[None, []]]
        self.space_pending = False

    def text(self, t):
        if not t:
            return
        t = t.replace("\xa0", " ")
        t = re.sub(r"[ \t\r\n\f]+", " ", t)
        runs = self.blocks[-1][1]
        if not runs or (runs[-1][0] == "t" and runs[-1][1].endswith(" ")):
            t = t.lstrip(" ")
        if not t:
            return
        if runs and runs[-1][0] == "t":
            runs[-1] = ("t", runs[-1][1] + t)
        else:
            runs.append(("t", t))

    def formula(self, f, display):
        if display:
            self.newblock("center")
            self.blocks[-1][1].append(("f", f.key, True))
            self.newblock(None)
        else:
            runs = self.blocks[-1][1]
            if runs and runs[-1][0] == "t" and runs[-1][1] and not runs[-1][1].endswith(" "):
                pass
            runs.append(("f", f.key, False))

    def newblock(self, align=None):
        cur = self.blocks[-1]
        if cur[1] and cur[1][-1][0] == "t":
            cur[1][-1] = ("t", cur[1][-1][1].rstrip(" "))
            if not cur[1][-1][1]:
                cur[1].pop()
        if not cur[1]:
            cur[0] = align
            return
        self.blocks.append([align, []])

    def result(self):
        out = []
        for al, runs in self.blocks:
            runs = [r for r in runs if not (r[0] == "t" and not r[1])]
            if runs and runs[-1][0] == "t":
                runs[-1] = ("t", runs[-1][1].rstrip())
            out.append((al, tuple(runs)))
        while out and not out[-1][1]:
            out.pop()
        while out and not out[0][1]:
            out.pop(0)
        # схлопываем повторяющиеся пустые строки
        res = []
        for b in out:
            if not b[1] and res and not res[-1][1]:
                continue
            res.append(b)
        return tuple(res)


def html_to_runs(html, size=12.0):
    from lxml import html as LH
    base = _source_url(html)
    frag = _fragment(html)
    try:
        root = LH.fragment_fromstring(frag, create_parent="div")
    except Exception:
        return None
    b = _Builder()
    found_any = [False]

    def walk(el):
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        cls = (el.get("class") or "") if tag else ""
        if tag in SKIP_TAGS:
            return
        if "katex" in cls.split() or tag == "math" or "MathJax" in cls or tag == "mjx-container":
            tex = None
            ann = el.xpath(".//annotation[@encoding='application/x-tex']")
            if ann:
                tex = ann[0].text_content()
            elif el.get("data-latex") or el.get("alttext"):
                tex = el.get("data-latex") or el.get("alttext")
            if tex:
                try:
                    f = F.from_latex(tex, 12.0)
                    disp = "display" in cls or el.get("display") == "block"
                    b.formula(f, disp)
                    found_any[0] = True
                    return
                except Exception:
                    pass
        if "katex-html" in cls:
            return
        if tag == "br":
            b.newblock()
        elif tag == "img":
            src = el.get("src") or ""
            alt = el.get("alt") or ""
            if src and (".svg" in src.lower() or "latex" in src.lower() or "math" in cls):
                try:
                    url = urljoin(base, src) if base else src
                    if url.startswith("data:image/svg"):
                        import base64
                        payload = url.split(",", 1)[1]
                        svg = base64.b64decode(payload).decode("utf-8") if ";base64" in url.split(",")[0] else payload
                    else:
                        svg = F.fetch_svg(url)
                    f = F.from_site_svg(svg, alt)
                    b.formula(f, "display" in cls)
                    found_any[0] = True
                except Exception:
                    b.text(" " + _alt_line(alt) + " ")
            elif alt:
                b.text(alt)
        elif tag in BLOCK_TAGS:
            b.newblock()
            if el.text:
                b.text(el.text)
            for ch in el:
                walk(ch)
                if ch.tail:
                    b.text(ch.tail)
            b.newblock()
            return
        else:
            if el.text:
                b.text(el.text)
            for ch in el:
                walk(ch)
                if ch.tail:
                    b.text(ch.tail)
            return
        return

    if root.text:
        b.text(root.text)
    for ch in root:
        walk(ch)
        if ch.tail:
            b.text(ch.tail)
    res = b.result()
    if not res:
        return None
    if not found_any[0]:
        return res
    return res


def _alt_line(alt):
    lines = [l.strip() for l in alt.splitlines() if l.strip() and not set(l.strip()) <= set("-√ ")]
    return " ".join(lines)


def text_to_runs(text, size=12.0):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = tuple((None, (("t", line),) if line else ()) for line in text.split("\n"))
    while blocks and not blocks[-1][1]:
        blocks = blocks[:-1]
    return blocks
